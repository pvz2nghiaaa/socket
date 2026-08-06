import os
import uuid
import socket
import hashlib
import time
import stat
import shutil
from src.protocol.rdt import RDTSender, RDTReceiver

def _get_absolute_path(base_dir: str, filename: str) -> str:
    """
    Bảo mật: Ngăn chặn Directory Traversal Attack bằng os.path.commonpath
    """
    abs_base = os.path.abspath(base_dir)
    cleaned_filename = filename.lstrip("/\\")
    safe_path = os.path.abspath(os.path.join(abs_base, cleaned_filename))
    
    # Kiểm tra safe_path có thực sự nằm trong abs_base hay không
    if os.path.commonpath([abs_base, safe_path]) != abs_base:
        raise ValueError("Security Alert: Lỗi truy cập đường dẫn không hợp lệ.")
    return safe_path

def get_list(directory: str) -> str:
    """Trả về danh sách đơn giản các file và thư mục trong thư mục được chỉ định."""
    files = os.listdir(directory)
    return "\r\n".join(files) + "\r\n"

def get_detailed_list(directory: str) -> str:
    """Trả về danh sách chi tiết định dạng Linux các file và thư mục."""
    lines = []
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        stat_info = os.stat(path)
        
        # Đọc quyền thực tế
        mode_str = stat.filemode(stat_info.st_mode)
        
        # Dung lượng
        size = stat_info.st_size
        
        # Thời gian sửa đổi gần nhất
        mtime = time.strftime("%b %d %H:%M", time.localtime(stat_info.st_mtime))
        
        lines.append(f"{mode_str}   1 owner    group    {size:10} {mtime} {name}")
        
    return "\r\n".join(lines) + "\r\n"

def get_size(path: str) -> int:
    """Trả về kích thước của file tính bằng byte."""
    if not os.path.exists(path):
        raise FileNotFoundError("File not found")
    if os.path.isdir(path):
        raise IsADirectoryError("Not a plain file")
    return os.path.getsize(path)

def get_mdtm(path: str) -> str:
    """Trả về thời gian sửa đổi cuối cùng của file dưới dạng chuỗi YYYYMMDDhhmmss (GMT)."""
    if not os.path.exists(path):
        raise FileNotFoundError("File not found")
    mtime = os.path.getmtime(path)
    return time.strftime("%Y%m%d%H%M%S", time.gmtime(mtime))

def get_single_file_detail(path: str) -> str:
    """Trả về thông tin chi tiết định dạng Linux của một file đơn lẻ."""
    if not os.path.exists(path):
        raise FileNotFoundError("File not found")
    
    stat_info = os.stat(path)
    mode_str = stat.filemode(stat_info.st_mode)
    size = stat_info.st_size
    mtime = time.strftime("%b %d %H:%M", time.localtime(stat_info.st_mtime))
    name = os.path.basename(path)
    
    return f"{mode_str}   1 owner    group    {size:10} {mtime} {name}\r\n"

def retr_file(base_dir: str, filename: str, data_socket: socket.socket, client_addr: tuple) -> str:
    """Tải file từ Server về Client (Download) qua RDT over UDP"""
    try:
        filepath = _get_absolute_path(base_dir, filename)
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

def stor_file(base_dir: str, filename: str, data_socket: socket.socket, append: bool = False) -> str:
    """Tải file từ Client lên Server (Upload - Ghi đè/Nối tiếp) qua RDT over UDP"""
    try:
        filepath = _get_absolute_path(base_dir, filename)
        print(f"[FileSystem] Initiating STOR/APPE for {filename} (Append: {append})")
        
        receiver = RDTReceiver(data_socket)
        file_mode = 'ab' if append else 'wb'
        receiver.receive_file(filepath, file_mode=file_mode)
        
        return "226 Transfer complete."
    except ValueError as e:
        return f"550 {e}"
    except Exception as e:
        print(f"[FileSystem] STOR/APPE Error: {e}")
        return "451 Requested action aborted."
    finally:
        data_socket.close()

def stou_file(base_dir: str, data_socket: socket.socket) -> tuple[str, str]:
    """Tải file lên Server với tên ngẫu nhiên (Unique Upload) qua RDT over UDP"""
    try:
        while True:
            unique_filename = f"file_{uuid.uuid4().hex[:8]}.bin"
            filepath = os.path.join(base_dir, unique_filename)
            if not os.path.exists(filepath):
                break
        
        print(f"[FileSystem] Initiating STOU, generated name: {unique_filename}")
        
        receiver = RDTReceiver(data_socket)
        receiver.receive_file(filepath, file_mode='wb')
        
        return f"250 FILE: {unique_filename}", unique_filename
    except Exception as e:
        print(f"[FileSystem] STOU Error: {e}")
        return "451 Requested action aborted.", ""
    finally:
        data_socket.close()

def delete_file(base_dir: str, filename: str) -> str:
    """Xóa file trên Server"""
    try:
        filepath = _get_absolute_path(base_dir, filename)
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

def rename_file(base_dir: str, old_filename: str, new_filename: str) -> str:
    """Đổi tên file/thư mục trên Server"""
    try:
        old_filepath = _get_absolute_path(base_dir, old_filename)
        new_filepath = _get_absolute_path(base_dir, new_filename)
        
        if not os.path.exists(old_filepath):
            return "550 Original file no longer exists."
            
        os.rename(old_filepath, new_filepath)
        print(f"[FileSystem] Renamed file from {old_filename} to {new_filename}")
        return "250 Requested file action okay, completed."
    except ValueError as e:
        return f"550 {e}"
    except Exception as e:
        print(f"[FileSystem] Rename error: {e}")
        return "553 Requested action not taken."

def calculate_hash(base_dir: str, filename: str, algorithm: str = 'MD5') -> str:
    """Tính mã băm (MD5/SHA256) của file trên Server"""
    try:
        filepath = _get_absolute_path(base_dir, filename)
        
        if not os.path.isfile(filepath):
            return "550 File not found or is a directory."
            
        algo_upper = algorithm.upper().replace('-', '')
        print(f"[FileSystem] Calculating {algo_upper} for {filename}...")
        
        if algo_upper == 'SHA256':
            hasher = hashlib.sha256()
        elif algo_upper == 'MD5':
            hasher = hashlib.md5()
        else:
            print(f"[FileSystem] HASH Error: Unsupported algorithm '{algorithm}'")
            return f"504 Unsupported hash algorithm '{algorithm}'."
            
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
                
        hash_hex = hasher.hexdigest()
        print(f"[FileSystem] HASH Result ({algo_upper}): {hash_hex}")
        return f"213 {hash_hex}"
        
    except ValueError as e:
        return f"550 {e}"
    except Exception as e:
        print(f"[FileSystem] HASH Error: {e}")
        return "450 Requested file action not taken."

def make_directory(base_dir: str, path: str) -> tuple[str, str]:
    """Tạo thư mục mới trên Server"""
    try:
        target_path = _get_absolute_path(base_dir, path)
        if os.path.exists(target_path):
            return "550 Directory already exists.", ""
            
        os.makedirs(target_path, exist_ok=True)
        rel_path = "/" + os.path.relpath(target_path, base_dir).replace("\\", "/").strip("/")
        return f'257 "{rel_path}" directory created.', rel_path
    except ValueError as e:
        return f"550 {e}", ""
    except Exception as e:
        return f"550 Create directory operation failed: {e}", ""

def remove_directory(base_dir: str, path: str) -> str:
    """Xóa thư mục trên Server"""
    try:
        target_path = _get_absolute_path(base_dir, path)
        if not os.path.exists(target_path) or not os.path.isdir(target_path):
            return "550 Remove directory operation failed: Directory does not exist."
            
        if target_path == base_dir:
            return "550 Cannot remove root directory."
            
        shutil.rmtree(target_path)
        print(f"[FileSystem] Removed directory: {path}")
        return "250 Directory and its contents successfully removed."
    except ValueError as e:
        return f"550 {e}"
    except Exception as e:
        return f"550 Remove directory operation failed: {e}"
