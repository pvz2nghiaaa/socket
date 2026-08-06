import os
import uuid
import hashlib
import time
import stat
import shutil

def get_absolute_path(base_dir: str, filename: str) -> str:
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

def generate_unique_filename(base_dir: str) -> str:
    """Sinh tên file độc nhất trong base_dir, tránh đè file cũ."""
    abs_base = os.path.abspath(base_dir)
    while True:
        unique_filename = f"file_{uuid.uuid4().hex[:8]}.bin"
        filepath = os.path.join(abs_base, unique_filename)
        if not os.path.exists(filepath):
            return unique_filename

def delete_file(base_dir: str, filename: str) -> None:
    """Xóa file trên Server"""
    filepath = get_absolute_path(base_dir, filename)
    if not os.path.exists(filepath):
        raise FileNotFoundError("File not found.")
    if os.path.isdir(filepath):
        raise IsADirectoryError("Cannot delete a directory.")
        
    os.remove(filepath)
    print(f"[FileSystem] Deleted file: {filename}")

def rename_file(base_dir: str, old_filename: str, new_filename: str) -> None:
    """Đổi tên file/thư mục trên Server"""
    old_filepath = get_absolute_path(base_dir, old_filename)
    new_filepath = get_absolute_path(base_dir, new_filename)
    
    if not os.path.exists(old_filepath):
        raise FileNotFoundError("Original file no longer exists.")
        
    os.rename(old_filepath, new_filepath)
    print(f"[FileSystem] Renamed file from {old_filename} to {new_filename}")

def calculate_hash(base_dir: str, filename: str, algorithm: str = 'MD5') -> str:
    """Tính mã băm (MD5/SHA256) của file trên Server và trả về chuỗi hash hex."""
    filepath = get_absolute_path(base_dir, filename)
    
    if not os.path.exists(filepath):
        raise FileNotFoundError("File not found.")
    if os.path.isdir(filepath):
        raise IsADirectoryError("Cannot calculate hash of a directory.")
        
    algo_upper = algorithm.upper().replace('-', '')
    print(f"[FileSystem] Calculating {algo_upper} for {filename}...")
    
    if algo_upper == 'SHA256':
        hasher = hashlib.sha256()
    elif algo_upper == 'MD5':
        hasher = hashlib.md5()
    else:
        print(f"[FileSystem] HASH Error: Unsupported algorithm '{algorithm}'")
        raise ValueError(f"Unsupported hash algorithm '{algorithm}'.")
        
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
            
    hash_hex = hasher.hexdigest()
    print(f"[FileSystem] HASH Result ({algo_upper}): {hash_hex}")
    return hash_hex

def make_directory(base_dir: str, path: str) -> str:
    """Tạo thư mục mới trên Server và trả về đường dẫn tương đối."""
    target_path = get_absolute_path(base_dir, path)
    if os.path.exists(target_path):
        raise FileExistsError("Directory already exists.")
        
    os.makedirs(target_path, exist_ok=True)
    rel_path = "/" + os.path.relpath(target_path, base_dir).replace("\\", "/").strip("/")
    return rel_path

def remove_directory(base_dir: str, path: str) -> None:
    """Xóa thư mục trên Server"""
    target_path = get_absolute_path(base_dir, path)
    abs_base = os.path.abspath(base_dir)
    
    if not os.path.exists(target_path) or not os.path.isdir(target_path):
        raise FileNotFoundError("Directory does not exist.")
        
    if target_path == abs_base:
        raise PermissionError("Cannot remove root directory.")
        
    shutil.rmtree(target_path)
    print(f"[FileSystem] Removed directory: {path}")
