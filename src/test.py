import os
import time
import socket
import threading
import hashlib
from src.server.file_system import calculate_hash
from src.protocol.rdt import RDTSender, RDTReceiver

# Cấu hình mạng Test
SERVER_IP = "127.0.0.1"
DATA_PORT = 8888
SERVER_DIR = "./server_storage"
CLIENT_DIR = "./client_storage"

def setup_directories():
    os.makedirs(SERVER_DIR, exist_ok=True)
    os.makedirs(CLIENT_DIR, exist_ok=True)

def generate_test_file(filepath, size_mb):
    """Tạo một file nhị phân ngẫu nhiên để test"""
    print(f"[*] Đang tạo file test {size_mb}MB...")
    with open(filepath, 'wb') as f:
        f.write(os.urandom(size_mb * 1024 * 1024))
    
    # Tính MD5 gốc
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        hasher.update(f.read())
    return hasher.hexdigest()

def mock_ftp_server():
    """Giả lập Data Plane của Server xử lý lệnh STOR"""
    # Mở port nhận dữ liệu
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((SERVER_IP, DATA_PORT))
    
    print("[Server] Đang đợi nhận file qua Data Channel...")
    # Kích hoạt RDTReceiver trực tiếp
    receiver = RDTReceiver(server_socket)
    receiver.receive_file(os.path.join(SERVER_DIR, "upload_test.bin"), file_mode='wb')
    server_socket.close()
    
    # Kích hoạt hàm HASH để kiểm tra
    hash_response = calculate_hash(SERVER_DIR, "upload_test.bin", "MD5")
    print(f"[Server] Kết quả HASH: {hash_response}")

def mock_ftp_client(client_filepath):
    """Giả lập Client đẩy file lên Server qua RDT"""
    time.sleep(1) # Chờ server khởi động socket
    
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest_addr = (SERVER_IP, DATA_PORT)
    
    print(f"[Client] Bắt đầu đẩy file '{client_filepath}' lên Server...")
    sender = RDTSender(client_socket, dest_addr)
    sender.send_file(client_filepath)
    client_socket.close()

if __name__ == "__main__":
    setup_directories()
    
    client_test_file = os.path.join(CLIENT_DIR, "dummy_video.mp4")
    original_md5 = generate_test_file(client_test_file, size_mb=5) # Test file 5MB
    
    print("="*50)
    print(f"[!] MD5 File Gốc (Client): {original_md5}")
    print("="*50)

    # Chạy Server trên 1 Thread độc lập
    server_thread = threading.Thread(target=mock_ftp_server)
    server_thread.start()

    # Chạy Client ở luồng chính
    mock_ftp_client(client_test_file)
    
    server_thread.join()
    
    print("="*50)
    print("✅ TEST HOÀN TẤT. Hãy đối chiếu mã MD5 của Server và Client ở trên!")
    
    # Dọn dẹp
    # os.remove(client_test_file)
    # os.remove(os.path.join(SERVER_DIR, "upload_test.bin"))