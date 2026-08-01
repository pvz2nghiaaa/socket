import socket
import os
from udp_packet import create_packet, parse_packet, FLAG_DATA, FLAG_ACK, FLAG_FIN

TIMEOUT_SECONDS = 2.0
PAYLOAD_SIZE = 1024  # chia file thành các khối size cố định để chia IP

def rdt_send_file(sock: socket.socket, dest_addr: tuple, file_path: str):
    """
    Gửi file sử dụng thuật toán RDT Stop-and-Wait (Tương ứng nhánh File Upload/Download)
    """
    # timeout
    sock.settimeout(TIMEOUT_SECONDS)
    seq_no = 0
    
    with open(file_path, 'rb') as f:
        while True:
            # read each chunk
            payload = f.read(PAYLOAD_SIZE)
            if not payload:
                break 
            
            packet = create_packet(seq_no=seq_no, ack_no=0, flags=FLAG_DATA, payload=payload)
            
            # 2. Stop-and-Wait
            ack_received = False
            while not ack_received:
                try:
                    # Send
                    sock.sendto(packet, dest_addr)
                    print(f"[Sender] Đã gửi Packet SEQ={seq_no}")
                    
                    # wait ACK
                    ack_data, _ = sock.recvfrom(2048)
                    parsed_ack = parse_packet(ack_data)
                    
                    # RDT: Bỏ qua nếu gói ACK bị lỗi (Corruption)
                    if parsed_ack['is_corrupted']:
                        print(f"[Sender] Phát hiện ACK lỗi. Chờ Timeout...")
                        continue
                        
                    # RDT: Xác nhận đúng ACK cho SEQ đang chờ
                    if parsed_ack['flags'] == FLAG_ACK and parsed_ack['ack_no'] == seq_no:
                        print(f"[Sender] Nhận thành công ACK={seq_no}")
                        ack_received = True
                        seq_no += 1  # Tịnh tiến SEQ cho gói tiếp theo
                        
                except socket.timeout:
                    # RDT: Cơ chế Timeout & Retransmit
                    print(f"[!] Timeout! Đang truyền lại (Retransmit) SEQ={seq_no}")
    
    # Gửi gói tin FIN để báo hiệu kết thúc luồng dữ liệu
    fin_packet = create_packet(seq_no=seq_no, ack_no=0, flags=FLAG_FIN)
    sock.sendto(fin_packet, dest_addr)
    print("[Sender] Hoàn tất quá trình truyền file.")


def rdt_receive_file(sock: socket.socket, save_path: str):
    """
    Nhận file sử dụng thuật toán RDT Stop-and-Wait
    """
    sock.settimeout(300.0) # timeout 300s = 5p
    expected_seq = 0
    
    with open(save_path, 'wb') as f:
        while True:
            try:
                data, addr = sock.recvfrom(2048)
                parsed_packet = parse_packet(data)
                
                # 1. RDT: Kiểm tra hỏng hóc (Corruption Detection)
                if parsed_packet['is_corrupted']:
                    print("[Receiver] Gói tin bị biến dạng (Corrupted). Bỏ qua.")
                    continue  # Không làm gì cả, ép Sender phải Timeout và gửi lại
                    
                # 2. Kiểm tra cờ FIN (Kết thúc luồng truyền)
                if parsed_packet['flags'] == FLAG_FIN:
                    print("[Receiver] Nhận được tín hiệu FIN. Kết thúc quá trình ghi file.")
                    break
                    
                # 3. Xử lý gói tin chứa dữ liệu
                if parsed_packet['flags'] == FLAG_DATA:
                    received_seq = parsed_packet['seq_no']
                    
                    # Trường hợp 1: Nhận đúng gói tin đang mong đợi
                    if received_seq == expected_seq:
                        f.write(parsed_packet['payload'])
                        print(f"[Receiver] Ghi thành công SEQ={received_seq} vào ổ cứng.")
                        expected_seq += 1
                        
                    # Trường hợp 2: RDT Deduplication (Nhận lại gói cũ do mất ACK trên đường về)
                    elif received_seq < expected_seq:
                        print(f"[Receiver] Phát hiện gói lặp (Duplicate) SEQ={received_seq}. Bỏ qua Payload.")
                        
                    # 4. Gửi ACK phản hồi 
                    # Dù là gói mới hay gói lặp, đều phải gửi lại ACK để Sender đi tiếp
                    ack_packet = create_packet(seq_no=0, ack_no=received_seq, flags=FLAG_ACK)
                    sock.sendto(ack_packet, addr)
                    
            except socket.timeout:
                print("[!] Lỗi mạng: Không nhận được dữ liệu quá lâu (Timeout).")
                break