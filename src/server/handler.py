class ClientSession:
    """
    Quản lý trạng thái phiên kết nối của từng Client ở phía Server
    """
    def __init__(self, control_socket):
        self.control_socket = control_socket # Socket TCP điều khiển
        self.mode = None # ACTIVE hay PASSIVE
        self.data_address = None # (ip, port) của Client
        self.data_socket = None # Socket UDP của server (passive)

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
import socket
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

def generate_pasv_response(server_ip: str):
    if server_ip == "0.0.0.0":
        server_ip = "127.0.0.1"
    # Tạo socket UDP, ipv4
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Bind vào port = 0 để hệ điều hành tự chọn cổng rảnh
    udp_socket.bind((server_ip, 0))
    _, assigned_port = udp_socket.getsockname()

    # Format lại IP và Port để gửi sang client
    ip = ",".join(server_ip.strip("."))
    p1 = assigned_port // 256
    p2 = assigned_port % 256
    response_msg = f"227 Entering Passive Mode ({ip},{p1},{p2})."

    return udp_socket, response_msg
