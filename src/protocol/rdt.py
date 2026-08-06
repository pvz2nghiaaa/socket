import os
import socket
import time
import select
from .udp_packet import create_packet, parse_packet, FLAG_DATA, FLAG_ACK, FLAG_FIN

WINDOW_SIZE = 4       
TIMEOUT_SECONDS = 2.0 
PAYLOAD_SIZE = 1024

class RDTSender:
    """Class quản lý tiến trình gửi dữ liệu bằng thuật toán Selective Repeat"""
    def __init__(self, sock: socket.socket, dest_addr: tuple):
        self.sock = sock
        self.dest_addr = dest_addr
        self.sock.setblocking(0)
        
    def send_file(self, file_path: str, control_socket: socket.socket = None, transfer_type: str = "I") -> bool:
        """
        Gửi file bằng Selective Repeat.
        Hỗ trợ chuyển đổi TYPE A (ASCII) và kiểm tra lệnh hủy ABOR thời gian thực.
        """
        # 1. Đọc và chuẩn hóa dữ liệu dựa trên transfer_type
        if transfer_type == "A":
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text_content = f.read()
            except Exception:
                with open(file_path, 'rb') as f:
                    text_content = f.read().decode('utf-8', errors='ignore')
            # Chuẩn hóa tất cả các dòng kết thúc bằng CRLF (\r\n) theo chuẩn FTP ASCII
            normalized = text_content.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
            file_data = normalized.encode('utf-8')
        else:
            with open(file_path, 'rb') as f:
                file_data = f.read()

        file_size = len(file_data)
        total_packets = (file_size + PAYLOAD_SIZE - 1) // PAYLOAD_SIZE if file_size > 0 else 0
        
        base = 0           
        next_seq_num = 0   
        timers = {}        
        acked = [False] * total_packets 
        
        print(f"[Sender] Started transmitting {total_packets} packets (Type: {transfer_type}) using Selective Repeat...")

        while base < total_packets:
            # 1. Trượt cửa sổ và gửi các gói tin mới
            while next_seq_num < base + WINDOW_SIZE and next_seq_num < total_packets:
                payload = file_data[next_seq_num * PAYLOAD_SIZE : (next_seq_num + 1) * PAYLOAD_SIZE]
                packet = create_packet(seq_no=next_seq_num, ack_no=0, flags=FLAG_DATA, payload=payload)
                self.sock.sendto(packet, self.dest_addr)
                timers[next_seq_num] = time.time() 
                print(f"[Sender] Sent Packet SEQ={next_seq_num}")
                next_seq_num += 1
                
            # 2. Lắng nghe phản hồi ACK hoặc lệnh ABOR trên kênh control
            socks_to_check = [self.sock]
            if control_socket:
                socks_to_check.append(control_socket)

            readable, _, _ = select.select(socks_to_check, [], [], 0.05)
            for ready_sock in readable:
                if ready_sock == control_socket:
                    try:
                        control_data = control_socket.recv(1024).decode('utf-8', errors='ignore').strip()
                        if control_data.upper() == 'ABOR':
                            print("[Sender] ABOR received. Aborting file transmission!")
                            control_socket.sendall(b"426 Connection closed; transfer aborted.\r\n")
                            control_socket.sendall(b"226 Abort successful.\r\n")
                            return False
                    except Exception as e:
                        print(f"[Sender] Control channel error during transfer: {e}")
                elif ready_sock == self.sock:
                    while True:
                        try:
                            ack_data, _ = self.sock.recvfrom(2048)
                            parsed_ack = parse_packet(ack_data)
                            
                            if not parsed_ack['is_corrupted'] and parsed_ack['flags'] == FLAG_ACK:
                                ack_seq = parsed_ack['ack_no']
                                
                                if 0 <= ack_seq < total_packets:
                                    if not acked[ack_seq]:
                                        print(f"[Sender] >> Successfully received ACK={ack_seq}")
                                        acked[ack_seq] = True
                                        if ack_seq in timers:
                                            del timers[ack_seq]
                                        
                                    # Cập nhật lại Base nếu gói tin đầu cửa sổ đã được ACK
                                    while base < total_packets and acked[base]:
                                        base += 1
                                        print(f"[Sender] Window slid to Base={base}")
                        except (BlockingIOError, socket.error):
                            break  
                        except Exception:
                            break 
                    
            # 3. Kiểm tra Timeout cho từng gói tin riêng lẻ trong cửa sổ
            current_time = time.time()
            for i in range(base, next_seq_num):
                if not acked[i] and i in timers:
                    if current_time - timers[i] > TIMEOUT_SECONDS:
                        print(f"[!] Timeout! Retransmitting SEQ={i}")
                        payload = file_data[i * PAYLOAD_SIZE : (i + 1) * PAYLOAD_SIZE]
                        packet = create_packet(seq_no=i, ack_no=0, flags=FLAG_DATA, payload=payload)
                        self.sock.sendto(packet, self.dest_addr)
                        timers[i] = time.time() 

        # 4. Truyền tín hiệu kết thúc (Gửi 3 lần để tránh thất lạc FIN)
        self.sock.setblocking(1) 
        fin_packet = create_packet(seq_no=total_packets, ack_no=0, flags=FLAG_FIN)
        for _ in range(3):
            self.sock.sendto(fin_packet, self.dest_addr)
            time.sleep(0.01)
        print("[Sender] File transmission complete (Selective Repeat).")
        return True

class RDTReceiver:
    """Class quản lý tiến trình nhận dữ liệu bằng thuật toán Selective Repeat"""
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.sock.setblocking(0)
        self.base = 0
        self.buffer = {} 
        
    def receive_file(self, save_path: str, file_mode: str = 'wb', control_socket: socket.socket = None, transfer_type: str = "I") -> bool:
        """
        Nhận file bằng Selective Repeat.
        Hỗ trợ chuyển đổi TYPE A (ASCII) và kiểm tra lệnh hủy ABOR thời gian thực.
        """
        print(f"[Receiver] Ready to receive file (Mode: {file_mode}, Type: {transfer_type})...")
        
        # Mở file ghi dữ liệu tạm
        f_mode = 'a' if file_mode == 'ab' else 'w'
        if transfer_type == 'I':
            f_mode += 'b'

        # Sử dụng encoding UTF-8 nếu lưu ở dạng text
        f = open(save_path, f_mode, encoding='utf-8', errors='ignore') if transfer_type == 'A' else open(save_path, f_mode)
        
        start_time = time.time()
        
        try:
            while True:
                # Kiểm tra timeout 300 giây của receiver
                if time.time() - start_time > 300.0:
                    print("[!] Network Error: Receiver Timeout.")
                    break

                socks_to_check = [self.sock]
                if control_socket:
                    socks_to_check.append(control_socket)

                readable, _, _ = select.select(socks_to_check, [], [], 0.5)
                
                aborted = False
                for ready_sock in readable:
                    if ready_sock == control_socket:
                        try:
                            control_data = control_socket.recv(1024).decode('utf-8', errors='ignore').strip()
                            if control_data.upper() == 'ABOR':
                                print("[Receiver] ABOR received. Aborting file reception!")
                                control_socket.sendall(b"426 Connection closed; transfer aborted.\r\n")
                                control_socket.sendall(b"226 Abort successful.\r\n")
                                aborted = True
                                break
                        except Exception as e:
                            print(f"[Receiver] Control channel error during transfer: {e}")
                    elif ready_sock == self.sock:
                        try:
                            data, addr = self.sock.recvfrom(2048)
                            parsed_packet = parse_packet(data)
                            
                            if parsed_packet['is_corrupted']:
                                print("[Receiver] Corrupted packet received. Discarded.")
                                continue
                                
                            if parsed_packet['flags'] == FLAG_FIN:
                                print("[Receiver] FIN signal received. Terminating.")
                                return True
                                
                            if parsed_packet['flags'] == FLAG_DATA:
                                seq = parsed_packet['seq_no']
                                
                                if self.base <= seq < self.base + WINDOW_SIZE:
                                    ack_packet = create_packet(seq_no=0, ack_no=seq, flags=FLAG_ACK)
                                    self.sock.sendto(ack_packet, addr)
                                    
                                    if seq not in self.buffer:
                                        self.buffer[seq] = parsed_packet['payload']
                                        print(f"[Receiver] Received and buffered SEQ={seq}")
                                        
                                    while self.base in self.buffer:
                                        payload = self.buffer[self.base]
                                        if transfer_type == 'A':
                                            text_data = payload.decode('utf-8', errors='ignore').replace('\r\n', '\n')
                                            f.write(text_data)
                                        else:
                                            f.write(payload)
                                            
                                        del self.buffer[self.base] 
                                        print(f"[Receiver] Written to disk SEQ={self.base}")
                                        self.base += 1
                                            
                                elif max(0, self.base - WINDOW_SIZE) <= seq < self.base:
                                    print(f"[Receiver] Duplicate packet SEQ={seq} received. Resending ACK.")
                                    ack_packet = create_packet(seq_no=0, ack_no=seq, flags=FLAG_ACK)
                                    self.sock.sendto(ack_packet, addr)
                        except (BlockingIOError, socket.error):
                            pass
                
                if aborted:
                    return False
        finally:
            f.close()
            
        return False