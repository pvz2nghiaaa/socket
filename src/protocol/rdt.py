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
        
    def send_file(self, file_path: str):
        file_size = os.path.getsize(file_path)
        total_packets = (file_size + PAYLOAD_SIZE - 1) // PAYLOAD_SIZE if file_size > 0 else 0
        
        base = 0           
        next_seq_num = 0   
        timers = {}        
        acked = [False] * total_packets 
        
        print(f"[Sender] Started transmitting {total_packets} packets using Selective Repeat...")

        with open(file_path, 'rb') as f:
            while base < total_packets:
                # 1. Trượt cửa sổ và gửi các gói tin mới
                while next_seq_num < base + WINDOW_SIZE and next_seq_num < total_packets:
                    f.seek(next_seq_num * PAYLOAD_SIZE)
                    payload = f.read(PAYLOAD_SIZE)
                    
                    packet = create_packet(seq_no=next_seq_num, ack_no=0, flags=FLAG_DATA, payload=payload)
                    self.sock.sendto(packet, self.dest_addr)
                    timers[next_seq_num] = time.time() 
                    print(f"[Sender] Sent Packet SEQ={next_seq_num}")
                    next_seq_num += 1
                    
                # 2. Lắng nghe phản hồi ACK không đồng bộ
                readable, _, _ = select.select([self.sock], [], [], 0.05)
                if readable:
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
                                            del timers[ack_seq] # Dọn dẹp bộ nhớ timer
                                        
                                    # Cập nhật lại Base nếu gói tin đầu cửa sổ đã được ACK
                                    while base < total_packets and acked[base]:
                                        base += 1
                                        print(f"[Sender] Window slid to Base={base}")
                        except (BlockingIOError, socket.error):
                            break  # Buffer đã trống hoặc không còn dữ liệu đọc
                        except Exception:
                            break 
                        
                # 3. Kiểm tra Timeout cho từng gói tin riêng lẻ trong cửa sổ
                current_time = time.time()
                for i in range(base, next_seq_num):
                    if not acked[i] and i in timers:
                        if current_time - timers[i] > TIMEOUT_SECONDS:
                            print(f"[!] Timeout! Retransmitting ONLY lost packet SEQ={i}")
                            
                            f.seek(i * PAYLOAD_SIZE)
                            payload = f.read(PAYLOAD_SIZE)
                            
                            packet = create_packet(seq_no=i, ack_no=0, flags=FLAG_DATA, payload=payload)
                            self.sock.sendto(packet, self.dest_addr)
                            timers[i] = time.time() # Reset timer

        # 4. Truyền tín hiệu kết thúc (Gửi 3 lần để tránh thất lạc FIN)
        self.sock.setblocking(1) 
        fin_packet = create_packet(seq_no=total_packets, ack_no=0, flags=FLAG_FIN)
        for _ in range(3):
            self.sock.sendto(fin_packet, self.dest_addr)
            time.sleep(0.01)
        print("[Sender] File transmission complete (Selective Repeat).")

class RDTReceiver:
    """Class quản lý tiến trình nhận dữ liệu bằng thuật toán Selective Repeat"""
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.sock.setblocking(1)
        self.sock.settimeout(300.0)
        self.base = 0
        self.buffer = {} 
        
    def receive_file(self, save_path: str, file_mode: str = 'wb'):
        print(f"[Receiver] Ready to receive file (Mode: {file_mode})...")
        
        with open(save_path, file_mode) as f:
            while True:
                try:
                    data, addr = self.sock.recvfrom(2048)
                    parsed_packet = parse_packet(data)
                    
                    if parsed_packet['is_corrupted']:
                        print("[Receiver] Corrupted packet received. Discarded.")
                        continue
                        
                    if parsed_packet['flags'] == FLAG_FIN:
                        print("[Receiver] FIN signal received. Terminating.")
                        break
                        
                    if parsed_packet['flags'] == FLAG_DATA:
                        seq = parsed_packet['seq_no']
                        
                        # Trường hợp 1: Nằm trong cửa sổ mong đợi [base, base + WINDOW_SIZE - 1]
                        if self.base <= seq < self.base + WINDOW_SIZE:
                            ack_packet = create_packet(seq_no=0, ack_no=seq, flags=FLAG_ACK)
                            self.sock.sendto(ack_packet, addr)
                            
                            if seq not in self.buffer:
                                self.buffer[seq] = parsed_packet['payload']
                                print(f"[Receiver] Received and buffered SEQ={seq}")
                                
                            # Xả liên tục dữ liệu từ buffer ra ổ cứng chừng nào base còn tồn tại trong buffer
                            while self.base in self.buffer:
                                f.write(self.buffer[self.base])
                                del self.buffer[self.base] 
                                print(f"[Receiver] Written to disk SEQ={self.base}")
                                self.base += 1
                                    
                        # Trường hợp 2: Nằm trong cửa sổ cũ [max(0, base - WINDOW_SIZE), base - 1]
                        elif max(0, self.base - WINDOW_SIZE) <= seq < self.base:
                            print(f"[Receiver] Duplicate packet SEQ={seq} received. Resending ACK.")
                            ack_packet = create_packet(seq_no=0, ack_no=seq, flags=FLAG_ACK)
                            self.sock.sendto(ack_packet, addr)
                            
                except socket.timeout:
                    print("[!] Network Error: Receiver Timeout.")
                    break