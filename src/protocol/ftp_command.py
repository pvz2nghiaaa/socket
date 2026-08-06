import os
import socket
from src.server import file_system

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
        if expected_pass == "" or expected_pass == arg or username == "anonymous":
            session.is_authenticated = True
            return "230 User logged in, proceed.\r\n"
        else:
            session.username = None
            return "530 Incorrect password.\r\n"
    else:
        # Default fallback: allow login
        session.is_authenticated = True
        return "230 User logged in, proceed.\r\n"

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
    res, _ = file_system.make_directory(session.root_directory, os.path.join(session.current_directory.lstrip("/"), arg))
    return res + "\r\n"

def handle_rmd(session, arg: str) -> str:
    if not arg:
        return "501 Syntax error in parameters or arguments.\r\n"
    return file_system.remove_directory(session.root_directory, os.path.join(session.current_directory.lstrip("/"), arg)) + "\r\n"

def handle_port(session, arg: str) -> str:
    return session.handle_port(arg)

def handle_pasv(session) -> str:
    return session.handle_pasv()

def handle_list(session) -> str:
    if not session.mode:
        return "425 Can't open data connection. No mode selected.\r\n"
    try:
        actual_path = os.path.join(session.root_directory, session.current_directory.lstrip("/"))
        directory_data = file_system.get_detailed_list(actual_path)
    except Exception as e:
        return f"450 Requested file action not taken. Error: {e}\r\n"
        
    session.control_socket.sendall(b"150 Opening ASCII mode data connection for file list.\r\n")
    try:
        session.send_udp_data(directory_data)
        return "226 Transfer complete.\r\n"
    except Exception as e:
        return f"426 Connection closed; transfer aborted. Error: {e}\r\n"

def handle_nlst(session) -> str:
    if not session.mode:
        return "425 Can't open data connection. No mode selected.\r\n"
    try:
        actual_path = os.path.join(session.root_directory, session.current_directory.lstrip("/"))
        directory_data = file_system.get_list(actual_path)
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
    return file_system.delete_file(session.root_directory, relative_path) + "\r\n"

def handle_rnfr(session, filename: str) -> str:
    try:
        relative_path = os.path.join(session.current_directory.lstrip("/"), filename)
        # Verify filepath is safe and exists
        safe_path = file_system._get_absolute_path(session.root_directory, relative_path)
        if os.path.exists(safe_path):
            session.rename_from_path = relative_path
            print(f"[FileSystem] RNFR received: {filename}")
            return "350 Requested file action pending further information.\r\n"
        return "550 File not found or is a directory.\r\n"
    except ValueError as e:
        return f"550 {e}\r\n"

def handle_rnto(session, new_filename: str) -> str:
    if not session.rename_from_path:
        return "503 Bad sequence of commands.\r\n"
    try:
        relative_new_path = os.path.join(session.current_directory.lstrip("/"), new_filename)
        # Check security on the target path
        _ = file_system._get_absolute_path(session.root_directory, relative_new_path)
        res = file_system.rename_file(session.root_directory, session.rename_from_path, relative_new_path)
        return res + "\r\n"
    except ValueError as e:
        return f"550 {e}\r\n"
    finally:
        session.rename_from_path = None

def handle_hash(session, arg: str) -> str:
    parts = arg.strip().split()
    if not parts:
        return "501 Syntax error in parameters or arguments.\r\n"
    filename = parts[0]
    algo = parts[1] if len(parts) > 1 else "MD5"
    relative_path = os.path.join(session.current_directory.lstrip("/"), filename)
    return file_system.calculate_hash(session.root_directory, relative_path, algo) + "\r\n"

def handle_retr(session, filename: str) -> str:
    if not session.mode:
        return "425 Can't open data connection. No mode selected.\r\n"
    
    if session.mode == "PASSIVE":
        if not session.data_socket:
            return "425 Can't open data connection. No passive socket.\r\n"
        if not session.data_address:
            try:
                # Wait for passive handshake from client
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

    session.control_socket.sendall(b"150 Opening UDP data connection for RETR.\r\n")
    try:
        relative_path = os.path.join(session.current_directory.lstrip("/"), filename)
        response = file_system.retr_file(session.root_directory, relative_path, data_socket, client_addr)
        return response + "\r\n"
    except Exception as e:
        return f"451 Requested action aborted: local error in processing. Error: {e}\r\n"
    finally:
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
                _, client_udp_addr = session.data_socket.recvfrom(1024)
                session.data_address = client_udp_addr
            except Exception as e:
                return f"425 Can't open data connection. Error: {e}\r\n"
        data_socket = session.data_socket
    else: # ACTIVE
        data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_ip, _ = session.control_socket.getsockname()
        data_socket.bind((server_ip, 0))

    cmd_name = "APPE" if append else "STOR"
    session.control_socket.sendall(f"150 Opening UDP data connection for {cmd_name}.\r\n".encode('utf-8'))
    try:
        relative_path = os.path.join(session.current_directory.lstrip("/"), filename)
        response = file_system.stor_file(session.root_directory, relative_path, data_socket, append=append)
        return response + "\r\n"
    except Exception as e:
        return f"451 Requested action aborted. Error: {e}\r\n"
    finally:
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
                _, client_udp_addr = session.data_socket.recvfrom(1024)
                session.data_address = client_udp_addr
            except Exception as e:
                return f"425 Can't open data connection. Error: {e}\r\n"
        data_socket = session.data_socket
    else: # ACTIVE
        data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_ip, _ = session.control_socket.getsockname()
        data_socket.bind((server_ip, 0))

    session.control_socket.sendall(b"150 Opening UDP data connection for STOU.\r\n")
    try:
        response, _ = file_system.stou_file(session.root_directory, data_socket)
        return response + "\r\n"
    except Exception as e:
        return f"451 Requested action aborted. Error: {e}\r\n"
    finally:
        if session.mode == "PASSIVE":
            session.data_socket = None
        session.mode = None
        session.data_address = None

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
            "LIST": "LIST           : List files details",
            "NLST": "NLST           : List file names",
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
            "HASH": "HASH <file>    : Get file checksum"
        }
        if cmd in help_docs:
            return f"214 {help_docs[cmd]}\r\n"
        else:
            return f"502 Unknown command '{cmd}'.\r\n"

    msg = (
        "214-The following commands are recognized:\r\n"
        " USER PASS CWD PWD MKD RMD QUIT HELP PORT PASV LIST NLST SIZE MDTM STAT RETR STOR APPE STOU DELE RNFR RNTO HASH\r\n"
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
        return handle_list(session)
    elif cmd == "NLST":
        return handle_nlst(session)
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
    else:
        return f"502 Command '{cmd}' not implemented.\r\n"
