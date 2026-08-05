import os
import time
import stat

def get_list(directory):
    files = os.listdir(directory)
    return "\r\n".join(files) + "\r\n"

def get_detailed_list(directory):
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
    """
    Trả về kích thước của file thường tính bằng byte.
    """
    if not os.path.exists(path):
        raise FileNotFoundError("File not found")
    if os.path.isdir(path):
        raise IsADirectoryError("Not a plain file")
    return os.path.getsize(path)

def get_mdtm(path: str) -> str:
    """
    Trả về thời gian sửa đổi cuối cùng của file dưới dạng chuỗi YYYYMMDDhhmmss (GMT).
    """
    if not os.path.exists(path):
        raise FileNotFoundError("File not found")
    mtime = os.path.getmtime(path)
    return time.strftime("%Y%m%d%H%M%S", time.gmtime(mtime))

def get_single_file_detail(path: str) -> str:
    """
    Trả về thông tin chi tiết định dạng Linux của một file đơn lẻ.
    """
    if not os.path.exists(path):
        raise FileNotFoundError("File not found")
    
    stat_info = os.stat(path)
    mode_str = stat.filemode(stat_info.st_mode)
    size = stat_info.st_size
    mtime = time.strftime("%b %d %H:%M", time.localtime(stat_info.st_mtime))
    name = os.path.basename(path)
    
    return f"{mode_str}   1 owner    group    {size:10} {mtime} {name}\r\n"
