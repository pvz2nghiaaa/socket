import socket
import time

SERVER_IP = "127.0.0.1"
SERVER_TCP_PORT = 2121

def run_additional_commands(tcp_socket):
    """
    Hàm bổ trợ gửi các lệnh SIZE, MDTM, STAT để test
    """
    print("\n--- KIỂM THỬ CÁC LỆNH HỆ THỐNG FILE (SIZE, MDTM, STAT) ---")
    
    # 1. Test STAT không đối số (Trạng thái Server)
    tcp_socket.sendall(b"STAT\r\n")
    print(f"[TCP] Gửi: STAT")
    print(f"[TCP] Server phản hồi:\n{tcp_socket.recv(2048).decode().strip()}\n")
    
    # 2. Tạo hoặc đặt 1 file tên 'test.txt' trong thư mục ftp_root để test các lệnh tiếp theo
    print("[Chú ý] Để test SIZE/MDTM/STAT với đối số, hãy chắc chắn có file 'test.txt' trong thư mục ftp_root.")
    
    # 3. Test SIZE với file 'test.txt'
    tcp_socket.sendall(b"SIZE test.txt\r\n")
    print(f"[TCP] Gửi: SIZE test.txt")
    print(f"[TCP] Server phản hồi: {tcp_socket.recv(1024).decode().strip()}\n")
    
    # 4. Test MDTM với file 'test.txt'
    tcp_socket.sendall(b"MDTM test.txt\r\n")
    print(f"[TCP] Gửi: MDTM test.txt")
    print(f"[TCP] Server phản hồi: {tcp_socket.recv(1024).decode().strip()}\n")
    
    # 5. Test STAT có đối số là 'test.txt' (Đọc chi tiết file qua TCP)
    tcp_socket.sendall(b"STAT test.txt\r\n")
    print(f"[TCP] Gửi: STAT test.txt")
    print(f"[TCP] Server phản hồi:\n{tcp_socket.recv(2048).decode().strip()}\n")
    print("---------------------------------------------------------\n")


def test_passive_mode():
    print("\n=== STARTING PASSIVE MODE TEST ===")
    
    # 1. Kết nối kênh điều khiển TCP
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.connect((SERVER_IP, SERVER_TCP_PORT))
    print(f"[TCP] Nhận lời chào: {tcp_socket.recv(1024).decode().strip()}")

    # 2. Gửi lệnh PASV
    tcp_socket.sendall(b"PASV\r\n")
    pasv_response = tcp_socket.recv(1024).decode().strip()
    print(f"[TCP] Server phản hồi PASV: {pasv_response}")

    try:
        addr_str = pasv_response.split('(')[1].split(')')[0]
        parts = addr_str.split(',')
        sv_udp_ip = ".".join(parts[:4])
        sv_udp_port = int(parts[4]) * 256 + int(parts[5])
        print(f"[Client] Server mở cổng UDP tại: {sv_udp_ip}:{sv_udp_port}")
    except Exception as e:
        print(f"[Lỗi] Không thể phân tách phản hồi PASV: {e}")
        tcp_socket.close()
        return

    # 3. Tạo socket UDP ở Client
    client_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_udp_socket.settimeout(5.0)

    # 4. Gửi lệnh LIST qua TCP
    tcp_socket.sendall(b"LIST\r\n")
    print(f"[TCP] Server phản hồi LIST: {tcp_socket.recv(1024).decode().strip()}")

    # 5. Gửi gói tin bắt tay (handshake) qua UDP
    print("[UDP] Đang gửi gói tin bắt tay (handshake)...")
    client_udp_socket.sendto(b"HANDSHAKE", (sv_udp_ip, sv_udp_port))

    # 6. Đọc dữ liệu thư mục qua UDP
    try:
        data, addr = client_udp_socket.recvfrom(4096)
        print("\n--- KẾT QUẢ DANH SÁCH FILE (Nhận qua UDP) ---")
        print(data.decode('utf-8'))
        print("--------------------------------------------\n")
    except socket.timeout:
        print("[Lỗi] Quá thời gian chờ (Timeout) nhận dữ liệu qua UDP.")

    # 7. Đọc phản hồi hoàn tất qua TCP
    print(f"[TCP] Server báo kết thúc: {tcp_socket.recv(1024).decode().strip()}")

    # 8. Thực hiện chạy kiểm thử các lệnh phụ (SIZE, MDTM, STAT)
    run_additional_commands(tcp_socket)

    # 9. Thoát
    tcp_socket.sendall(b"QUIT\r\n")
    print(f"[TCP] Thoát: {tcp_socket.recv(1024).decode().strip()}")
    tcp_socket.close()
    client_udp_socket.close()


def test_active_mode():
    print("\n=== STARTING ACTIVE MODE TEST ===")
    
    # 1. Tạo socket UDP và bind ngẫu nhiên ở Client
    client_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_udp_socket.bind((SERVER_IP, 0))
    client_ip, client_port = client_udp_socket.getsockname()
    client_udp_socket.settimeout(5.0)
    print(f"[Client] Cổng UDP của Client đã mở tại: {client_ip}:{client_port}")

    # 2. Kết nối kênh TCP
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.connect((SERVER_IP, SERVER_TCP_PORT))
    print(f"[TCP] Nhận lời chào: {tcp_socket.recv(1024).decode().strip()}")

    # 3. Gửi lệnh PORT
    ip_formatted = client_ip.replace(".", ",")
    p1 = client_port // 256
    p2 = client_port % 256
    port_cmd = f"PORT {ip_formatted},{p1},{p2}\r\n"
    
    tcp_socket.sendall(port_cmd.encode('utf-8'))
    print(f"[TCP] Gửi: {port_cmd.strip()}")
    print(f"[TCP] Server phản hồi PORT: {tcp_socket.recv(1024).decode().strip()}")

    # 4. Gửi lệnh LIST
    tcp_socket.sendall(b"LIST\r\n")
    print(f"[TCP] Server phản hồi LIST: {tcp_socket.recv(1024).decode().strip()}")

    # 5. Hứng dữ liệu UDP gửi từ Server
    try:
        data, addr = client_udp_socket.recvfrom(4096)
        print("\n--- KẾT QUẢ DANH SÁCH FILE (Nhận qua UDP) ---")
        print(data.decode('utf-8'))
        print("--------------------------------------------\n")
    except socket.timeout:
        print("[Lỗi] Quá thời gian chờ (Timeout) nhận dữ liệu qua UDP.")

    # 6. Đọc phản hồi hoàn tất qua TCP
    print(f"[TCP] Server báo kết thúc: {tcp_socket.recv(1024).decode().strip()}")

    # 7. Thực hiện chạy kiểm thử các lệnh phụ (SIZE, MDTM, STAT)
    run_additional_commands(tcp_socket)

    # 8. Thoát
    tcp_socket.sendall(b"QUIT\r\n")
    print(f"[TCP] Thoát: {tcp_socket.recv(1024).decode().strip()}")
    tcp_socket.close()
    client_udp_socket.close()


if __name__ == "__main__":
    print("Chọn chế độ kiểm thử:")
    print("1. Kiểm thử Passive Mode (PASV) + SIZE/MDTM/STAT")
    print("2. Kiểm thử Active Mode (PORT) + SIZE/MDTM/STAT")
    choice = input("Lựa chọn (1 hoặc 2): ").strip()
    
    if choice == "1":
        test_passive_mode()
    elif choice == "2":
        test_active_mode()
    else:
        print("Lựa chọn không hợp lệ!")
