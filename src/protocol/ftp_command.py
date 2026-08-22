import os
import socket
from src.server import file_system
from src.protocol.rdt import RDTSender, RDTReceiver

# Default user dictionary: username -> password
DEFAULT_USERS = {
    "anonymous": "123",
    "admin": "admin",
    "user": "123456"
}

def parse_command(raw_command: str) -> tuple[str, str]:
    """
    Parses a raw FTP command string into a (command, argument) tuple.
    Example: "CWD /path/to/dir" -> ("CWD", "/path/to/dir")
    """
    if not raw_command:
        return "", ""
    parts = raw_command.strip().split(maxsplit=1)
    cmd = parts[0].upper()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return cmd, arg

def handle_user(session, arg: str) -> str:
    if not arg:
        return "501 Syntax error in parameters or arguments.\r\n"
    if session.is_authenticated:
        return "530 Can't change user while logged in.\r\n"
    session.username = arg
    return f"331 User name {arg} okay, need password.\r\n"

def handle_pass(session, arg: str) -> str:
    if session.is_authenticated:
        return "230 Already logged in.\r\n"
    if not session.username:
        return "503 Login with USER first.\r\n"
    
    username = session.username
    expected_pass = DEFAULT_USERS.get(username)
    
    if username in DEFAULT_USERS:
        if expected_pass == arg:
            session.is_authenticated = True
            user_dir = os.path.abspath(os.path.join(session.base_root_directory, username))
            os.makedirs(user_dir, exist_ok=True)
            session.root_directory = user_dir
            session.current_directory = "/"
            return "230 User logged in, proceed.\r\n"
        else:
            session.username = None
            return "530 Incorrect password.\r\n"
    else:
        session.username = None
        return "530 User not found.\r\n"

def handle_pwd(session) -> str:
    return f'257 "{session.current_directory}" is current directory.\r\n'

def handle_cwd(session, arg: str) -> str:
    if not arg:
        return "501 Syntax error in parameters or arguments.\r\n"
    
    try:
        if arg.startswith("/") or arg.startswith("\\"):
            target_path = os.path.abspath(os.path.join(session.root_directory, arg.lstrip("/\\")))
        else:
            current_abs = os.path.abspath(os.path.join(session.root_directory, session.current_directory.lstrip("/\\")))
            target_path = os.path.abspath(os.path.join(current_abs, arg))
            
        if os.path.commonpath([session.root_directory, target_path]) != session.root_directory:
            return "550 Permission denied: Cannot navigate outside root directory.\r\n"
            
        if os.path.exists(target_path) and os.path.isdir(target_path):
            rel = os.path.relpath(target_path, session.root_directory)
            if rel == ".":
                session.current_directory = "/"
            else:
                session.current_directory = "/" + rel.replace("\\", "/").strip("/")
            return f'250 Directory successfully changed to "{session.current_directory}".\r\n'
        else:
            return "550 Failed to change directory: Directory does not exist.\r\n"
    except Exception as e:
        return f"550 Failed to change directory. Error: {e}\r\n"

def handle_mkd(session, arg: str) -> str:
    if not arg:
        return "501 Syntax error in parameters or arguments.\r\n"
    try:
        rel_path = file_system.make_directory(session.root_directory, os.path.join(session.current_directory.lstrip("/"), arg))
        return f'257 "{rel_path}" directory created.\r\n'
    except FileExistsError:
        return "550 Directory already exists.\r\n"
    except Exception as e:
        return f"550 Create directory operation failed: {e}\r\n"

def handle_rmd(session, arg: str) -> str:
    if not arg:
        return "501 Syntax error in parameters or arguments.\r\n"
    try:
        file_system.remove_directory(session.root_directory, os.path.join(session.current_directory.lstrip("/"), arg))
        return "250 Directory and its contents successfully removed.\r\n"
    except FileNotFoundError:
        return "550 Remove directory operation failed: Directory does not exist.\r\n"
    except PermissionError as e:
        return f"550 {e}\r\n"
    except Exception as e:
        return f"550 Remove directory operation failed: {e}\r\n"

def handle_port(session, arg: str) -> str:
    return session.handle_port(arg)

def handle_pasv(session) -> str:
    return session.handle_pasv()

def handle_list(session, arg: str = "") -> str:
    if not session.mode:
        return "425 Can't open data connection. No mode selected.\r\n"
    try:
        if arg:
            if arg.startswith("/") or arg.startswith("\\"):
                target_path = os.path.abspath(os.path.join(session.root_directory, arg.lstrip("/\\")))
            else:
                current_abs = os.path.abspath(os.path.join(session.root_directory, session.current_directory.lstrip("/\\")))
                target_path = os.path.abspath(os.path.join(current_abs, arg))
        else:
            target_path = os.path.abspath(os.path.join(session.root_directory, session.current_directory.lstrip("/\\")))
            
        if os.path.commonpath([session.root_directory, target_path]) != session.root_directory:
            return "550 Permission denied.\r\n"
            
        if not os.path.exists(target_path):
            return "550 Path does not exist.\r\n"
            
        if os.path.isdir(target_path):
            directory_data = file_system.get_detailed_list(target_path)
        else:
            directory_data = file_system.get_single_file_detail(target_path)
    except Exception as e:
        return f"450 Requested file action not taken. Error: {e}\r\n"
        
    session.control_socket.sendall(b"150 Opening ASCII mode data connection for file list.\r\n")
    try:
        session.send_udp_data(directory_data)
        return "226 Transfer complete.\r\n"
    except Exception as e:
        return f"426 Connection closed; transfer aborted. Error: {e}\r\n"

def handle_nlst(session, arg: str = "") -> str:
    if not session.mode:
        return "425 Can't open data connection. No mode selected.\r\n"
    try:
        if arg:
            if arg.startswith("/") or arg.startswith("\\"):
                target_path = os.path.abspath(os.path.join(session.root_directory, arg.lstrip("/\\")))
            else:
                current_abs = os.path.abspath(os.path.join(session.root_directory, session.current_directory.lstrip("/\\")))
                target_path = os.path.abspath(os.path.join(current_abs, arg))
        else:
            target_path = os.path.abspath(os.path.join(session.root_directory, session.current_directory.lstrip("/\\")))
            
        if os.path.commonpath([session.root_directory, target_path]) != session.root_directory:
            return "550 Permission denied.\r\n"
            
        if not os.path.exists(target_path):
            return "550 Path does not exist.\r\n"
            
        if os.path.isdir(target_path):
            directory_data = file_system.get_list(target_path)
        else:
            directory_data = os.path.basename(target_path) + "\r\n"
    except Exception as e:
        return f"450 Requested file action not taken. Error: {e}\r\n"
        
    session.control_socket.sendall(b"150 Opening ASCII mode data connection for file list.\r\n")
    try:
        session.send_udp_data(directory_data)
        return "226 Transfer complete.\r\n"
    except Exception as e:
        return f"426 Connection closed; transfer aborted. Error: {e}\r\n"

def handle_size(session, filename: str) -> str:
    try:
        actual_path = os.path.join(session.root_directory, session.current_directory.lstrip("/"), filename)
        size = file_system.get_size(actual_path)
        return f"213 {size}\r\n"
    except FileNotFoundError:
        return "550 File not found.\r\n"
    except IsADirectoryError:
        return "550 Not a plain file.\r\n"
    except Exception as e:
        return f"550 Could not get file size. Error: {e}\r\n"

def handle_mdtm(session, filename: str) -> str:
    try:
        actual_path = os.path.join(session.root_directory, session.current_directory.lstrip("/"), filename)
        formatted_time = file_system.get_mdtm(actual_path)
        return f"213 {formatted_time}\r\n"
    except FileNotFoundError:
        return "550 File not found.\r\n"
    except Exception as e:
        return f"550 Could not get modification time. Error: {e}\r\n"

def handle_stat(session, path: str = "") -> str:
    path = path.strip()
    if not path:
        status_info = (
            "211-Server Status:\r\n"
            " Type: FTP Control Channel (TCP)\r\n"
            " Data Channel: Reliable UDP (RDT)\r\n"
            f" Current Directory: {session.current_directory}\r\n"
            "211 End of status.\r\n"
        )
        return status_info
    try:
        actual_path = os.path.join(session.root_directory, session.current_directory.lstrip("/"), path)
        if os.path.isdir(actual_path):
            details = file_system.get_detailed_list(actual_path)
        else:
            details = file_system.get_single_file_detail(actual_path)
        return f"211-Status of {path}:\r\n{details}211 End of status.\r\n"
    except FileNotFoundError:
        return "550 File or directory not found.\r\n"
    except Exception as e:
        return f"450 Failed to get status. Error: {e}\r\n"

def handle_dele(session, filename: str) -> str:
    relative_path = os.path.join(session.current_directory.lstrip("/"), filename)
    try:
        file_system.delete_file(session.root_directory, relative_path)
        return "250 Requested file action okay, completed.\r\n"
    except FileNotFoundError:
        return "550 File not found.\r\n"
    except IsADirectoryError:
        return "550 Cannot delete a directory.\r\n"
    except Exception as e:
        return f"450 Requested file action not taken. Error: {e}\r\n"

def handle_rnfr(session, filename: str) -> str:
    try:
        relative_path = os.path.join(session.current_directory.lstrip("/"), filename)
        # Verify filepath is safe and exists
        safe_path = file_system.get_absolute_path(session.root_directory, relative_path)
        if os.path.exists(safe_path):
            session.rename_from_path = relative_path
            print(f"[FileSystem] RNFR received: {filename}")
            return "350 Requested file action pending further information.\r\n"
        return "550 File not found.\r\n"
    except ValueError as e:
        return f"550 {e}\r\n"

def handle_rnto(session, new_filename: str) -> str:
    if not session.rename_from_path:
        return "503 Bad sequence of commands.\r\n"
    try:
        relative_new_path = os.path.join(session.current_directory.lstrip("/"), new_filename)
        # Check security on the target path
        _ = file_system.get_absolute_path(session.root_directory, relative_new_path)
        file_system.rename_file(session.root_directory, session.rename_from_path, relative_new_path)
        return "250 Requested file action okay, completed.\r\n"
    except FileNotFoundError:
        return "550 Original file no longer exists.\r\n"
    except ValueError as e:
        return f"550 {e}\r\n"
    except Exception as e:
        return f"553 Requested action not taken. Error: {e}\r\n"
    finally:
        session.rename_from_path = None

def handle_hash(session, arg: str) -> str:
    parts = arg.strip().split()
    if not parts:
        return "501 Syntax error in parameters or arguments.\r\n"
    filename = parts[0]
    algo = parts[1] if len(parts) > 1 else "MD5"
    relative_path = os.path.join(session.current_directory.lstrip("/"), filename)
    try:
        hash_hex = file_system.calculate_hash(session.root_directory, relative_path, algo)
        return f"213 {hash_hex}\r\n"
    except FileNotFoundError:
        return "550 File not found.\r\n"
    except IsADirectoryError:
        return "550 Cannot calculate hash of a directory.\r\n"
    except ValueError as e:
        return f"504 {e}\r\n"
    except Exception as e:
        return f"450 Requested file action not taken. Error: {e}\r\n"

def handle_retr(session, filename: str) -> str:
    if not session.mode:
        return "425 Can't open data connection. No mode selected.\r\n"
    
    if session.mode == "PASSIVE":
        if not session.data_socket:
            return "425 Can't open data connection. No passive socket.\r\n"
        if not session.data_address:
            try:
                # Wait for passive handshake from client (with a 10s timeout to prevent deadlocks)
                session.data_socket.settimeout(10.0)
                _, client_udp_addr = session.data_socket.recvfrom(1024)
                session.data_address = client_udp_addr
            except Exception as e:
                return f"425 Can't open data connection. Error: {e}\r\n"
        data_socket = session.data_socket
        client_addr = session.data_address
    else: # ACTIVE
        data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_ip, _ = session.control_socket.getsockname()
        data_socket.bind((server_ip, 0))
        client_addr = session.data_address

    try:
        relative_path = os.path.join(session.current_directory.lstrip("/"), filename)
        filepath = file_system.get_absolute_path(session.root_directory, relative_path)
        
        if not os.path.isfile(filepath):
            return "550 File not found or is a directory.\r\n"
            
        print(f"[FileSystem] Initiating RETR for {filename}")
        session.control_socket.sendall(b"150 Opening UDP data connection for RETR.\r\n")
        
        # Start RDTSender to transmit file via UDP
        sender = RDTSender(data_socket, client_addr)
        success = sender.send_file(filepath, control_socket=session.control_socket, transfer_type=session.transfer_type)
        
        if not success:
            return ""  # Response already sent by RDT loop (426 + 226)
            
        return "226 Transfer complete.\r\n"
    except ValueError as e:
        return f"550 {e}\r\n"
    except Exception as e:
        print(f"[ftp_command] RETR Error: {e}")
        return "451 Requested action aborted: local error in processing.\r\n"
    finally:
        data_socket.close()
        if session.mode == "PASSIVE":
            session.data_socket = None
        session.mode = None
        session.data_address = None

def handle_stor(session, filename: str, append: bool = False) -> str:
    if not session.mode:
        return "425 Can't open data connection. No mode selected.\r\n"
    
    if session.mode == "PASSIVE":
        if not session.data_socket:
            return "425 Can't open data connection. No passive socket.\r\n"
        if not session.data_address:
            try:
                # Wait for passive handshake from client (with a 10s timeout to prevent deadlocks)
                session.data_socket.settimeout(10.0)
                _, client_udp_addr = session.data_socket.recvfrom(1024)
                session.data_address = client_udp_addr
            except Exception as e:
                return f"425 Can't open data connection. Error: {e}\r\n"
        data_socket = session.data_socket
    else: # ACTIVE
        data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_ip, _ = session.control_socket.getsockname()
        data_socket.bind((server_ip, 0))
        try:
            data_socket.sendto(b"HANDSHAKE", session.data_address)
        except Exception as e:
            print(f"[Server Error] Failed to send Active handshake: {e}")

    cmd_name = "APPE" if append else "STOR"
    try:
        relative_path = os.path.join(session.current_directory.lstrip("/"), filename)
        filepath = file_system.get_absolute_path(session.root_directory, relative_path)
        
        print(f"[FileSystem] Initiating {cmd_name} for {filename}")
        session.control_socket.sendall(f"150 Opening UDP data connection for {cmd_name}.\r\n".encode('utf-8'))
        
        # Start RDTReceiver to write file from UDP stream
        receiver = RDTReceiver(data_socket)
        file_mode = 'ab' if append else 'wb'
        success = receiver.receive_file(filepath, file_mode=file_mode, control_socket=session.control_socket, transfer_type=session.transfer_type)
        
        if not success:
            return ""  # Response already sent by RDT loop (426 + 226)
            
        return "226 Transfer complete.\r\n"
    except ValueError as e:
        return f"550 {e}\r\n"
    except Exception as e:
        print(f"[ftp_command] {cmd_name} Error: {e}")
        return "451 Requested action aborted.\r\n"
    finally:
        data_socket.close()
        if session.mode == "PASSIVE":
            session.data_socket = None
        session.mode = None
        session.data_address = None

def handle_stou(session) -> str:
    if not session.mode:
        return "425 Can't open data connection. No mode selected.\r\n"
    
    if session.mode == "PASSIVE":
        if not session.data_socket:
            return "425 Can't open data connection. No passive socket.\r\n"
        if not session.data_address:
            try:
                # Wait for passive handshake from client (with a 10s timeout to prevent deadlocks)
                session.data_socket.settimeout(10.0)
                _, client_udp_addr = session.data_socket.recvfrom(1024)
                session.data_address = client_udp_addr
            except Exception as e:
                return f"425 Can't open data connection. Error: {e}\r\n"
        data_socket = session.data_socket
    else: # ACTIVE
        data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_ip, _ = session.control_socket.getsockname()
        data_socket.bind((server_ip, 0))
        try:
            data_socket.sendto(b"HANDSHAKE", session.data_address)
        except Exception as e:
            print(f"[Server Error] Failed to send Active handshake: {e}")

    try:
        unique_filename = file_system.generate_unique_filename(session.root_directory)
        filepath = file_system.get_absolute_path(session.root_directory, unique_filename)
        
        print(f"[FileSystem] Initiating STOU, generated name: {unique_filename}")
        session.control_socket.sendall(b"150 Opening UDP data connection for STOU.\r\n")
        
        # Start RDTReceiver to write unique file
        receiver = RDTReceiver(data_socket)
        success = receiver.receive_file(filepath, file_mode='wb', control_socket=session.control_socket, transfer_type=session.transfer_type)
        
        if not success:
            return ""  # Response already sent by RDT loop (426 + 226)
            
        return f"250 FILE: {unique_filename}\r\n"
    except Exception as e:
        print(f"[ftp_command] STOU Error: {e}")
        return "451 Requested action aborted.\r\n"
    finally:
        data_socket.close()
        if session.mode == "PASSIVE":
            session.data_socket = None
        session.mode = None
        session.data_address = None

def handle_cdup(session) -> str:
    return handle_cwd(session, "..")

def handle_noop(session) -> str:
    return "200 Command OK.\r\n"

def handle_type(session, arg: str) -> str:
    if not arg:
        return "501 Syntax error in parameters or arguments.\r\n"
    t = arg.upper()
    if t in ("A", "I"):
        session.transfer_type = t
        return f"200 Type set to {t}.\r\n"
    return f"504 Command not implemented for that parameter '{arg}'.\r\n"

def handle_mode(session, arg: str) -> str:
    if not arg:
        return "501 Syntax error in parameters or arguments.\r\n"
    m = arg.upper()
    if m in ("S", "B", "C"):
        session.transfer_mode = m
        return f"200 Mode set to {m}.\r\n"
    return f"504 Command not implemented for that parameter '{arg}'.\r\n"

def handle_abor(session) -> str:
    return "225 No transfer in progress.\r\n"

def handle_quit(session) -> str:
    session.is_authenticated = False
    session.username = None
    return "QUIT_SIGNAL"

def handle_help(session, arg: str = "") -> str:
    if arg:
        cmd = arg.upper()
        help_docs = {
            "USER": "USER <username> : Specify user for authentication",
            "PASS": "PASS <password> : Specify password for authentication",
            "CWD":  "CWD <dir>      : Change working directory",
            "PWD":  "PWD            : Print working directory",
            "MKD":  "MKD <dir>      : Make directory",
            "RMD":  "RMD <dir>      : Remove directory",
            "PORT": "PORT <ip,p1,p2> : Setup active data channel connection",
            "PASV": "PASV           : Setup passive data channel connection",
            "LIST": "LIST [path]    : List files details",
            "NLST": "NLST [path]    : List file names",
            "QUIT": "QUIT           : Terminate connection",
            "HELP": "HELP [command] : Display help info",
            "SIZE": "SIZE <file>    : Get file size",
            "MDTM": "MDTM <file>    : Get file modification time",
            "STAT": "STAT [path]    : Get status of server or file",
            "RETR": "RETR <file>    : Download file via RDT over UDP",
            "STOR": "STOR <file>    : Upload file via RDT over UDP",
            "APPE": "APPE <file>    : Append to file via RDT over UDP",
            "STOU": "STOU           : Unique file upload via RDT over UDP",
            "DELE": "DELE <file>    : Delete file",
            "RNFR": "RNFR <file>    : Rename from",
            "RNTO": "RNTO <file>    : Rename to",
            "HASH": "HASH <file>    : Get file checksum",
            "CDUP": "CDUP           : Change working directory to parent directory",
            "NOOP": "NOOP           : No-operation keep-alive ping",
            "TYPE": "TYPE <A|I>     : Set transfer type (ASCII or Binary)",
            "MODE": "MODE <S|B|C>   : Set transfer mode (Stream, Block, Compressed)",
            "ABOR": "ABOR           : Abort the current data transfer"
        }
        if cmd in help_docs:
            return f"214 {help_docs[cmd]}\r\n"
        else:
            return f"502 Unknown command '{cmd}'.\r\n"

    msg = (
        "214-The following commands are recognized:\r\n"
        " USER PASS CWD PWD MKD RMD QUIT HELP PORT PASV LIST NLST SIZE MDTM STAT RETR STOR APPE STOU DELE RNFR RNTO HASH CDUP NOOP TYPE MODE ABOR\r\n"
        "214 Help OK.\r\n"
    )
    return msg

def process_ftp_command(session, raw_command: str) -> str:
    """
    Parses a raw command line and dispatches to the appropriate handler.
    Returns the message to send back to the client.
    """
    cmd, arg = parse_command(raw_command)
    if not cmd:
        return "500 Syntax error, command unrecognized.\r\n"

    # Yêu cầu xác thực trước khi chạy các lệnh hệ thống
    public_commands = ("USER", "PASS", "QUIT", "HELP")
    if cmd not in public_commands and not session.is_authenticated:
        return "530 Please login with USER and PASS first.\r\n"

    # Command Dispatcher
    if cmd == "USER":
        return handle_user(session, arg)
    elif cmd == "PASS":
        return handle_pass(session, arg)
    elif cmd == "PWD":
        return handle_pwd(session)
    elif cmd == "CWD":
        return handle_cwd(session, arg)
    elif cmd == "MKD":
        return handle_mkd(session, arg)
    elif cmd == "RMD":
        return handle_rmd(session, arg)
    elif cmd == "PORT":
        return handle_port(session, arg)
    elif cmd == "PASV":
        return handle_pasv(session)
    elif cmd == "LIST":
        return handle_list(session, arg)
    elif cmd == "NLST":
        return handle_nlst(session, arg)
    elif cmd == "SIZE":
        return handle_size(session, arg)
    elif cmd == "MDTM":
        return handle_mdtm(session, arg)
    elif cmd == "STAT":
        return handle_stat(session, arg)
    elif cmd == "DELE":
        return handle_dele(session, arg)
    elif cmd == "RNFR":
        return handle_rnfr(session, arg)
    elif cmd == "RNTO":
        return handle_rnto(session, arg)
    elif cmd == "HASH":
        return handle_hash(session, arg)
    elif cmd == "RETR":
        return handle_retr(session, arg)
    elif cmd == "STOR":
        return handle_stor(session, arg, append=False)
    elif cmd == "APPE":
        return handle_stor(session, arg, append=True)
    elif cmd == "STOU":
        return handle_stou(session)
    elif cmd == "QUIT":
        return handle_quit(session)
    elif cmd == "HELP":
        return handle_help(session, arg)
    elif cmd == "CDUP":
        return handle_cdup(session)
    elif cmd == "NOOP":
        return handle_noop(session)
    elif cmd == "TYPE":
        return handle_type(session, arg)
    elif cmd == "MODE":
        return handle_mode(session, arg)
    elif cmd == "ABOR":
        return handle_abor(session)
    else:
        return f"502 Command '{cmd}' not implemented.\r\n"
