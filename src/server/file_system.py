import os
import uuid
import socket
import hashlib
from protocol.rdt import RDTSender, RDTReceiver

class FileCommandHandler:
    """Class quản lý thao tác I/O ổ cứng và kết nối luồng truyền tải Data Plane"""
    
    def __init__(self, base_directory: str):
        self.base_dir = os.path.abspath(base_directory)
        self.rename_from_path = None
        
        # Tạo thư mục gốc lưu trữ data trên Server nếu chưa có
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)

    def _get_absolute_path(self, filename: str) -> str:
        """
        Bảo mật: Ngăn chặn Directory Traversal Attack bằng os.path.commonpath
        """
        safe_path = os.path.abspath(os.path.join(self.base_dir, filename))
        
        # Kiểm tra safe_path có thực sự nằm trong base_dir hay không
        if os.path.commonpath([self.base_dir, safe_path]) != self.base_dir:
            raise ValueError("Security Alert: Lỗi truy cập đường dẫn không hợp lệ.")
        return safe_path

    def handle_RETR(self, filename: str, data_socket: socket.socket, client_addr: tuple) -> str:
        """Tải file từ Server về Client (Download)"""
        try:
            filepath = self._get_absolute_path(filename)
            if not os.path.isfile(filepath):
                return "550 File not found or is a directory."
                
            print(f"[FileSystem] Initiating RETR for {filename}")
            
            # Khởi tạo RDTSender để đẩy file qua UDP
            sender = RDTSender(data_socket, client_addr)
            sender.send_file(filepath)
            
            return "226 Transfer complete."
        except ValueError as e:
            return f"550 {e}"
        except Exception as e:
            print(f"[FileSystem] RETR Error: {e}")
            return "451 Requested action aborted: local error in processing."
        finally:
            # Đảm bảo Data Channel được đóng sau khi truyền xong
            data_socket.close()

    def handle_STOR(self, filename: str, data_socket: socket.socket) -> str:
        """Tải file từ Client lên Server (Upload - Ghi đè)"""
        try:
            filepath = self._get_absolute_path(filename)
            print(f"[FileSystem] Initiating STOR for {filename}")
            
            receiver = RDTReceiver(data_socket)
            receiver.receive_file(filepath, file_mode='wb')
            
            return "226 Transfer complete."
        except ValueError as e:
            return f"550 {e}"
        except Exception as e:
            print(f"[FileSystem] STOR Error: {e}")
            return "451 Requested action aborted."
        finally:
            data_socket.close()

    def handle_APPE(self, filename: str, data_socket: socket.socket) -> str:
        """Tải file từ Client lên Server (Upload - Ghi nối tiếp)"""
        try:
            filepath = self._get_absolute_path(filename)
            print(f"[FileSystem] Initiating APPE for {filename}")
            
            receiver = RDTReceiver(data_socket)
            receiver.receive_file(filepath, file_mode='ab')
            
            return "226 Transfer complete."
        except ValueError as e:
            return f"550 {e}"
        except Exception as e:
            print(f"[FileSystem] APPE Error: {e}")
            return "451 Requested action aborted."
        finally:
            data_socket.close()

    def handle_STOU(self, data_socket: socket.socket) -> str:
        """Tải file lên Server với tên ngẫu nhiên (Unique Upload)"""
        try:
            # Sinh tên file độc nhất, tránh đè file cũ
            while True:
                unique_filename = f"file_{uuid.uuid4().hex[:8]}.bin"
                filepath = os.path.join(self.base_dir, unique_filename)
                if not os.path.exists(filepath):
                    break
            
            print(f"[FileSystem] Initiating STOU, generated name: {unique_filename}")
            
            receiver = RDTReceiver(data_socket)
            receiver.receive_file(filepath, file_mode='wb')
            
            return f"250 FILE: {unique_filename}"
        except Exception as e:
            print(f"[FileSystem] STOU Error: {e}")
            return "451 Requested action aborted."
        finally:
            data_socket.close()


    def handle_DELE(self, filename: str) -> str:
        """Xóa file trên Server"""
        try:
            filepath = self._get_absolute_path(filename)
            if os.path.isfile(filepath):
                os.remove(filepath)
                print(f"[FileSystem] Deleted file: {filename}")
                return "250 Requested file action okay, completed."
            return "550 File not found or is a directory."
        except ValueError as e:
            return f"550 {e}"
        except Exception as e:
            print(f"[FileSystem] Delete error: {e}")
            return "450 Requested file action not taken."

    def handle_RNFR(self, filename: str) -> str:
        """Bước 1 của đổi tên file: Chọn file cần đổi (Rename From)"""
        try:
            filepath = self._get_absolute_path(filename)
            if os.path.isfile(filepath):
                self.rename_from_path = filepath
                print(f"[FileSystem] RNFR received: {filename}")
                return "350 Requested file action pending further information."
            return "550 File not found or is a directory."
        except ValueError as e:
            return f"550 {e}"

    def handle_RNTO(self, new_filename: str) -> str:
        """Bước 2 của đổi tên file: Đặt tên mới (Rename To)"""
        if not self.rename_from_path:
            return "503 Bad sequence of commands."
            
        try:
            if not os.path.exists(self.rename_from_path):
                return "550 Original file no longer exists."

            new_filepath = self._get_absolute_path(new_filename)
            os.rename(self.rename_from_path, new_filepath)
            print(f"[FileSystem] Renamed file to: {new_filename}")
            
            return "250 Requested file action okay, completed."
        except ValueError as e:
            return f"550 {e}"
        except Exception as e:
            print(f"[FileSystem] Rename error: {e}")
            return "553 Requested action not taken."
        finally:
            # Luôn giải phóng biến tạm dù thành công hay thất bại
            self.rename_from_path = None
            
    def handle_HASH(self, filename: str, algorithm: str = 'MD5') -> str:
        """
        Tính mã băm của file trên Server để Client đối chiếu tính toàn vẹn.
        Hỗ trợ thuật toán MD5 hoặc SHA256. Trả về lỗi 504 nếu thuật toán không hợp lệ.
        """
        try:
            filepath = self._get_absolute_path(filename)
            
            # Chỉ tính hash nếu là file hợp lệ
            if not os.path.isfile(filepath):
                return "550 File not found or is a directory."
                
            # Chuẩn hóa tên thuật toán (Hỗ trợ cả 'SHA-256' và 'SHA256')
            algo_upper = algorithm.upper().replace('-', '')
            print(f"[FileSystem] Calculating {algo_upper} for {filename}...")
            
            # Kiểm tra thuật toán hỗ trợ
            if algo_upper == 'SHA256':
                hasher = hashlib.sha256()
            elif algo_upper == 'MD5':
                hasher = hashlib.md5()
            else:
                print(f"[FileSystem] HASH Error: Unsupported algorithm '{algorithm}'")
                return f"504 Unsupported hash algorithm '{algorithm}'."
                
            # Đọc file theo chunk 8KB để tối ưu hóa bộ nhớ cho file lớn
            with open(filepath, 'rb') as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
                    
            hash_hex = hasher.hexdigest()
            print(f"[FileSystem] HASH Result ({algo_upper}): {hash_hex}")
            
            # Trả về mã 213 (File Status) kèm chuỗi hash
            return f"213 {hash_hex}"
            
        except ValueError as e:
            return f"550 {e}"
        except Exception as e:
            print(f"[FileSystem] HASH Error: {e}")
            return "450 Requested file action not taken."