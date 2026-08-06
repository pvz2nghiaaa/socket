import socket
import os
from src.protocol import ftp_command

class ClientSession:
    """
    Quản lý trạng thái phiên kết nối của từng Client ở phía Server.
    Tất cả các trạng thái và dữ liệu tạm thời (bao gồm rename path) đều nằm ở đây.
    """
    def __init__(self, control_socket: socket.socket, root_dir: str = "./ftp_root"):
        self.control_socket = control_socket

        # Kênh dữ liệu (Data Channel)
        self.mode = None  # ACTIVE hoặc PASSIVE
        self.data_address = None  # (ip, port) của Client
        self.data_socket = None  # Socket UDP của server (khi ở PASSIVE mode)
        
        # Trạng thái xác thực (Authentication)
        self.username = None
        self.is_authenticated = False

        # Quản lý đường dẫn (File System directories)
        self.root_directory = os.path.abspath(root_dir)
        self.current_directory = "/"
        self.rename_from_path = None  # State lưu trữ path cũ khi RNFR chờ RNTO

        os.makedirs(self.root_directory, exist_ok=True)

    def handle_port(self, arg: str) -> str:
        """
        Xử lý lệnh PORT (Active mode): Client mở cổng và gửi cấu hình IP, Port cho Server.
        """
        try:
            ip, port = parse_port_command(arg)
            self.mode = "ACTIVE"
            self.data_address = (ip, port)
            
            # Đóng socket cũ nếu đang mở
            if self.data_socket:
                self.data_socket.close()
                self.data_socket = None

            return "200 PORT command successful.\r\n"
        except Exception as e:
            return f"501 Syntax error in parameters or arguments. Error: {e}\r\n"

    def handle_pasv(self) -> str:
        """
        Xử lý lệnh PASV (Passive mode): Server mở một cổng UDP ngẫu nhiên và phản hồi lại IP, Port cho Client.
        """
        try:
            if self.data_socket:
                self.data_socket.close()
            udp_socket, response_msg = generate_pasv_response(self.control_socket)
            self.mode = "PASSIVE"
            self.data_socket = udp_socket
            self.data_address = None  # Sẽ cập nhật khi nhận packet bắt tay từ Client
            
            return response_msg + "\r\n"
        except Exception as e:
            return f"425 Can't open data connection. Error: {e}\r\n"

    def send_udp_data(self, data_str: str):
        """
        Gửi dữ liệu chuỗi (ví dụ LIST, NLST) qua socket UDP dựa trên chế độ Active/Passive hiện hành.
        """
        data_bytes = data_str.encode('utf-8')
        
        if self.mode == "PASSIVE":
            if not self.data_socket:
                raise ValueError("Passive data socket is not initialized.")
            # Chờ nhận 1 gói tin bắt tay (handshake) rỗng nếu chưa có địa chỉ của Client
            if not self.data_address:
                _, client_udp_addr = self.data_socket.recvfrom(1024)
                self.data_address = client_udp_addr
                
            self.data_socket.sendto(data_bytes, self.data_address)
            
        elif self.mode == "ACTIVE":
            if not self.data_address:
                raise ValueError("Active data address is not configured.")
            # Trong Active Mode, Server tự tạo một socket UDP tạm để chủ động gửi dữ liệu sang Client
            temp_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            temp_udp_socket.sendto(data_bytes, self.data_address)
            temp_udp_socket.close()

def parse_port_command(arg: str) -> tuple[str, int]:
    """
    Phân tích cú pháp lệnh PORT.
    Ví dụ: "127,0,0,1,192,168" -> ("127.0.0.1", 49320)
    """
    parts = arg.strip().split(',')
    if len(parts) != 6:
        raise ValueError("PORT command must contain exactly 6 comma-separated fields")
    if not all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
        raise ValueError("PORT command parameters must be integers between 0 and 255")

    ip = ".".join(parts[:4])
    port = (int(parts[4]) << 8) + int(parts[5])
    return ip, port

def generate_pasv_response(control_socket: socket.socket) -> tuple[socket.socket, str]:
    """
    Tạo socket UDP ngẫu nhiên ở phía Server và trả về tuple chứa socket đó cùng chuỗi phản hồi PASV 227.
    """
    server_ip, _ = control_socket.getsockname()
    if server_ip == "0.0.0.0":
        server_ip = "127.0.0.1"
        
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.bind((server_ip, 0))
    _, assigned_port = udp_socket.getsockname()

    ip = server_ip.replace(".", ",")
    p1 = assigned_port // 256
    p2 = assigned_port % 256
    response_msg = f"227 Entering Passive Mode ({ip},{p1},{p2})."

    return udp_socket, response_msg

def handle_client_session(client_socket, client_addr, shutdown_signal):
    """
    Hàm quản lý vòng lặp làm việc độc lập của mỗi Client.
    """
    print(f"[Server] Client connected from {client_addr}")
    
    # 1. Gửi lời chào
    client_socket.sendall(b"220 Welcome to Hybrid FTP Server.\r\n")
    
    # 2. Khởi tạo session
    session = ClientSession(client_socket)
    client_socket.settimeout(300.0)

    while not shutdown_signal.is_set():
        try:
            # 3. Đọc dữ liệu lệnh từ Client
            data = client_socket.recv(1024)
            if not data:
                break  # Client ngắt kết nối chủ động
                
            command_text = data.decode('utf-8').strip()
            if not command_text:
                continue
                
            # 4. Ủy thác xử lý qua module ftp_command
            response = ftp_command.process_ftp_command(session, command_text)
            
            # Xử lý tín hiệu thoát đặc biệt
            if response == "QUIT_SIGNAL":
                client_socket.sendall(b"221 Goodbye.\r\n")
                break
                
            if response:
                client_socket.sendall(response.encode('utf-8'))
            
        except socket.timeout:
            print(f"[!] Timeout: Client {client_addr} ngắt hoạt động.")
            break
        except ConnectionResetError:
            print(f"[!] Connection Reset: Mất kết nối đột ngột với {client_addr}.")
            break
        except Exception as e:
            print(f"[!] Lỗi kết nối client {client_addr}: {e}")
            break
            
    # Dọn dẹp đóng socket
    if session.data_socket:
        session.data_socket.close()
    client_socket.close()
    print(f"[Server] Closed connection with {client_addr}")
