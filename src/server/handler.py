import socket
import os
from . import file_system
class ClientSession:
    """
    Quản lý trạng thái phiên kết nối của từng Client ở phía Server
    """
    def __init__(self, control_socket: socket.socket, root_dir: str = "./ftp_root"):
        # Socket TCP điều khiển
        self.control_socket = control_socket

        # Data channel
        self.mode = None # ACTIVE hay PASSIVE
        self.data_address = None # (ip, port) của Client
        self.data_socket = None # Socket UDP của server (passive)
        
        # Authentication 
        self.username = None
        self.is_authenticated = False

        # Thư mục hệ thống
        self.root_directory = root_dir
        self.current_directory = "/"

        os.makedirs(self.root_directory, exist_ok=True)

    def handle_port(self, arg: str) -> str:
        """
        Xử lý lệnh PORT (active)
        """
        try:
            ip, port = parse_port_command(arg)
            self.mode = "ACTIVE"
            self.data_address = (ip,port)
            if self.data_socket:
                self.data_socket.close()
                sef.data_socket = None

            return "200 PORT command successfully.\r\n"
        except Exception as e:
            return f"501 Syntax error in parameters or arguments. Error: {e}\r\n"

    def handle_pasv(self) -> str:
        """
        Xử lý lệnh PASV: mở cổng UDP của Server
        """
        try:
            if self.data_socket:
                self.data_socket.close()
            udp_socket, response_msg = generate_pasv_response(self.control_socket)
            self.mode = "PASSIVE"
            self.data_socket = udp_socket
            self.data_address = None # Sẽ cập nhật từ gói tin UDP đầu tiên của client
            
            return response_msg
        except Exception as e:
            return f"425 Can't open data connection. Error: {e}\r\n"

    def handle_list(self) -> str:
        """
        Xử lý lệnh LIST: gửi danh sách file và thư mục CHI TIẾT (dạng Linux) qua UDP
        """
        # 1. Kiểm tra xem Client đã cấu hình kết nối Data Channel (Active/Passive) chưa
        if not self.mode:
            return "425 Can't open data connection. No mode selected.\r\n"
        # 2. Lấy dữ liệu chi tiết từ file_system backend
        try:
            actual_path = os.path.join(self.root_directory, self.current_directory.lstrip("/"))
            directory_data = file_system.get_detailed_list(actual_path)
        except Exception as e:
            return f"450 Requested file action not taken. Error: {e}\r\n"
        # 3. Gửi mã 150 báo hiệu chuẩn bị truyền dữ liệu qua TCP
        self.control_socket.sendall(b"150 Opening ASCII mode data connection for file list.\r\n")
        # 4. Thực hiện truyền dữ liệu qua kênh UDP
        try:
            self._send_udp_data(directory_data)
            # 5. Truyền xong thành công, trả về mã 226 để luồng chính gửi qua TCP
            return "226 Transfer complete.\r\n"
        except Exception as e:
            return f"426 Connection closed; transfer aborted. Error: {e}\r\n"
    
    def handle_nlst(self) -> str:
        """
        Xử lý lệnh NLST: gửi danh sách TÊN file và thư mục qua UDP
        """
        if not self.mode:
            return "425 Can't open data connection. No mode selected.\r\n"
        try:
            actual_path = os.path.join(self.root_directory, self.current_directory.lstrip("/"))
            directory_data = file_system.get_list(self.current_directory)
        except Exception as e:
            return f"450 Requested file action not taken. Error: {e}\r\n"
        self.control_socket.sendall(b"150 Opening ASCII mode data connection for file list.\r\n")
        try:
            self._send_udp_data(directory_data)
            return "226 Transfer complete.\r\n"
        except Exception as e:
            return f"426 Connection closed; transfer aborted. Error: {e}\r\n"

    def handle_size(self, filename: str) -> str:
        """
        Xử lý lệnh SIZE: gọi file_system để đo dung lượng
        """
        try:
            actual_path = os.path.join(self.root_directory, self.current_directory.lstrip("/"), filename)
            size = file_system.get_size(actual_path)
            return f"213 {size}\r\n"
        except FileNotFoundError:
            return "550 File not found.\r\n"
        except IsADirectoryError:
            return "550 Not a plain file.\r\n"
        except Exception as e:
            return f"550 Could not get file size. Error: {e}\r\n"

    def handle_mdtm(self, filename: str) -> str:
        """
        Xử lý lệnh MDTM: gọi file_system để lấy thời gian chỉnh sửa
        """
        try:
            actual_path = os.path.join(self.root_directory, self.current_directory.lstrip("/"), filename)
            formatted_time = file_system.get_mdtm(actual_path)
            return f"213 {formatted_time}\r\n"
        except FileNotFoundError:
            return "550 File not found.\r\n"
        except Exception as e:
            return f"550 Could not get modification time. Error: {e}\r\n"
    
    def handle_stat(self, path: str = "") -> str:
        """
        Xử lý lệnh STAT: trả về thông tin trạng thái qua TCP
        """
        path = path.strip()
        
        # Nếu STAT không truyền đường dẫn -> trả về thông tin tổng quan Server
        if not path:
            status_info = (
                "211-Server Status:\r\n"
                " Type: FTP Control Channel (TCP)\r\n"
                " Data Channel: Reliable UDP (RDT)\r\n"
                f" Current Directory: {self.current_directory}\r\n"
                "211 End of status.\r\n"
            )
            return status_info
        # Nếu STAT truyền đường dẫn -> lấy thông tin chi tiết qua TCP
        try:
            actual_path = os.path.join(self.root_directory, self.current_directory.lstrip("/"), path)
            if os.path.isdir(actual_path):
                details = file_system.get_detailed_list(actual_path)
            else:
                details = file_system.get_single_file_detail(actual_path)
            return f"211-Status of {path}:\r\n{details}211 End of status.\r\n"
        except FileNotFoundError:
            return "550 File or directory not found.\r\n"
        except Exception as e:
            return f"450 Failed to get status. Error: {e}\r\n"

    def _send_udp_data(self, data_str: str):
        """
        Hàm bổ trợ gửi dữ liệu qua socket UDP dựa trên chế độ Active/Passive hiện hành.
        """
        data_bytes = data_str.encode('utf-8')
        
        if self.mode == "PASSIVE":
            # Nếu chưa có địa chỉ đích của Client, chờ nhận 1 gói tin bắt tay đầu tiên
            if not self.data_address:
                # Nhận gói tin rỗng để lấy thông tin IP/Port từ client gửi tới cổng UDP
                _, client_udp_addr = self.data_socket.recvfrom(1024)
                self.data_address = client_udp_addr
                
            self.data_socket.sendto(data_bytes, self.data_address)
            
        elif self.mode == "ACTIVE":
            # Trong Active Mode, Server tự tạo một socket UDP tạm để chủ động gửi dữ liệu sang Client
            temp_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            temp_udp_socket.sendto(data_bytes, self.data_address)
            temp_udp_socket.close()
    
def parse_port_command(arg: str) -> tuple[str, int]:
    """
    Input: "127,0,0,1,192,168"
    Output: ("127.0.0.1", 49320)
    """
    parts = arg.strip().split(',')
    if len(parts) != 6:
        raise ValueError("PORT command must contain exactly 6 comma-seperated fields")
    if not all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
        raise ValueError("PORT command parameters must be integers between 0 and 255")

    ip = ".".join(parts[:4])
    port = (int(parts[4]) << 8) + int(parts[5])
    return ip, port

def generate_pasv_response(control_socket: socket.socket) -> tuple[socket.socket, str]:
    """
    Tạo socket UDP ngẫu nhiên ở phía Server và tạo chuỗi phản hồi PASV 227.
    """
    # 1. Lấy IP thực tế từ socket điều khiển TCP
    server_ip, _ = control_socket.getsockname()
    if server_ip == "0.0.0.0":
        server_ip = "127.0.0.1"
    # Tạo socket UDP, ipv4
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Bind vào port = 0 để hệ điều hành tự chọn cổng rảnh
    udp_socket.bind((server_ip, 0))
    _, assigned_port = udp_socket.getsockname()

    # Format lại IP và Port để gửi sang client
    ip = server_ip.replace(".", ",")
    p1 = assigned_port // 256
    p2 = assigned_port % 256
    response_msg = f"227 Entering Passive Mode ({ip},{p1},{p2})."

    return udp_socket, response_msg

def handle_client_session(client_socket, client_addr, shutdown_signal):
    """
    Hàm xử lí độc lập cho luồng mỗi client
    """
    #1 Gửi lời chào
    client_socket.sendall(b"220 Welcome to Hybrid FTP Server.\r\n")
    #2 Khởi tạo session
    session = ClientSession(client_socket)
    client_socket.settimeout(300.0)

    while not shutdown_signal.is_set():
        try:
            # 3. Đọc lệnh từ Client
            data = client_socket.recv(1024)
            if not data:
                break # Client ngắt kết nối
                
            command_text = data.decode('utf-8').strip()
            
            if ' ' in command_text:
                cmd, arg = command_text.split(' ', 1)
            else:
                cmd = command_text
                arg = ""
                
            cmd = cmd.upper()
            
            # Điều phối lệnh (ví dụ xử lý PORT/PASV)
            if cmd == "PORT":
                response = session.handle_port(arg)
            elif cmd == "PASV":
                response = session.handle_pasv()
            elif cmd == "QUIT":
                client_socket.sendall(b"221 Goodbye.\r\n")
                break
            elif cmd == "LIST":
                response = session.handle_list()
            elif cmd == "NLST":
                response = session.handle_nlst()
            elif cmd == "STAT":
                response = session.handle_stat(arg)
            elif cmd == "SIZE":
                response = session.handle_size(arg)
            elif cmd == "MDTM":
                response = session.handle_mdtm(arg)
            else:
                response = "502 Command not implemented.\r\n"
                
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
