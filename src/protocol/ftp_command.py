import os
import shutil

# Default user dictionary: username -> password
DEFAULT_USERS = {
    "anonymous": "123",
    "admin": "admin",
    "user": "123456"
}


class FTPSessionState:
    """
    Manages session state for an FTP client (login status, user, working directories).
    """
    def __init__(self, root_dir: str = None, users: dict = None):
        self.username: str | None = None
        self.is_logged_in: bool = False
        self.user_pending: str | None = None
        self.root_dir: str = os.path.abspath(root_dir) if root_dir else os.getcwd()
        self.current_dir: str = self.root_dir
        self.users: dict = users if users is not None else DEFAULT_USERS

    def get_relative_path(self) -> str:
        """Returns the current working directory relative to root_dir with forward slashes."""
        rel = os.path.relpath(self.current_dir, self.root_dir)
        if rel == ".":
            return "/"
        return "/" + rel.replace("\\", "/").strip("/")


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


def handle_user(session: FTPSessionState, arg: str) -> tuple[int, str]:
    """Handles USER command."""
    if not arg:
        return 501, "501 Syntax error in parameters or arguments."

    if session.is_logged_in:
        return 530, "530 Can't change user while logged in."

    session.user_pending = arg
    return 331, f"331 User name {arg} okay, need password."


def handle_pass(session: FTPSessionState, arg: str) -> tuple[int, str]:
    """Handles PASS command."""
    if session.is_logged_in:
        return 230, "230 Already logged in."

    if not session.user_pending:
        return 503, "503 Login with USER first."

    username = session.user_pending
    expected_pass = session.users.get(username)

    if username in session.users:
        if expected_pass == "" or expected_pass == arg or username == "anonymous":
            session.is_logged_in = True
            session.username = username
            session.user_pending = None
            return 230, "230 User logged in, proceed."
        else:
            session.user_pending = None
            return 530, "530 Incorrect password."
    else:
        # Allow default login for unlisted user
        session.is_logged_in = True
        session.username = username
        session.user_pending = None
        return 230, "230 User logged in, proceed."


def handle_pwd(session: FTPSessionState) -> tuple[int, str]:
    """Handles PWD command."""
    if not session.is_logged_in:
        return 530, "530 Please login with USER and PASS."

    rel_path = session.get_relative_path()
    return 257, f'257 "{rel_path}" is current directory.'


def handle_cwd(session: FTPSessionState, arg: str) -> tuple[int, str]:
    """Handles CWD command."""
    if not session.is_logged_in:
        return 530, "530 Please login with USER and PASS."

    if not arg:
        return 501, "501 Syntax error in parameters or arguments."

    if arg.startswith("/") or arg.startswith("\\"):
        target_path = os.path.abspath(os.path.join(session.root_dir, arg.lstrip("/\\")))
    else:
        target_path = os.path.abspath(os.path.join(session.current_dir, arg))

    if not target_path.startswith(session.root_dir):
        return 550, "550 Permission denied: Cannot navigate outside root directory."

    if os.path.exists(target_path) and os.path.isdir(target_path):
        session.current_dir = target_path
        rel_path = session.get_relative_path()
        return 250, f'250 Directory successfully changed to "{rel_path}".'
    else:
        return 550, "550 Failed to change directory: Directory does not exist."


def handle_mkd(session: FTPSessionState, arg: str) -> tuple[int, str]:
    """Handles MKD command (Make Directory)."""
    if not session.is_logged_in:
        return 530, "530 Please login with USER and PASS."

    if not arg:
        return 501, "501 Syntax error in parameters or arguments."

    if arg.startswith("/") or arg.startswith("\\"):
        target_path = os.path.abspath(os.path.join(session.root_dir, arg.lstrip("/\\")))
    else:
        target_path = os.path.abspath(os.path.join(session.current_dir, arg))

    if not target_path.startswith(session.root_dir):
        return 550, "550 Permission denied."

    if os.path.exists(target_path):
        return 550, "550 Directory already exists."

    try:
        os.makedirs(target_path, exist_ok=True)
        rel_path = "/" + os.path.relpath(target_path, session.root_dir).replace("\\", "/").strip("/")
        return 257, f'257 "{rel_path}" directory created.'
    except Exception as e:
        return 550, f"550 Create directory operation failed: {e}"


def handle_rmd(session: FTPSessionState, arg: str) -> tuple[int, str]:
    """Handles RMD command (Remove Directory)."""
    if not session.is_logged_in:
        return 530, "530 Please login with USER and PASS."

    if not arg:
        return 501, "501 Syntax error in parameters or arguments."

    if arg.startswith("/") or arg.startswith("\\"):
        target_path = os.path.abspath(os.path.join(session.root_dir, arg.lstrip("/\\")))
    else:
        target_path = os.path.abspath(os.path.join(session.current_dir, arg))

    if not target_path.startswith(session.root_dir):
        return 550, "550 Permission denied."

    if not os.path.exists(target_path) or not os.path.isdir(target_path):
        return 550, "550 Remove directory operation failed: Directory does not exist."

    if target_path == session.root_dir:
        return 550, "550 Cannot remove root directory."

    try:
        os.rmdir(target_path)
        return 250, "250 Remove directory operation successful."
    except OSError:
        try:
            shutil.rmtree(target_path)
            return 250, "250 Directory and its contents successfully removed."
        except Exception as e:
            return 550, f"550 Remove directory operation failed: {e}"


def handle_quit(session: FTPSessionState) -> tuple[int, str]:
    """Handles QUIT command."""
    session.is_logged_in = False
    session.user_pending = None
    return 221, "221 Goodbye."


def handle_help(session: FTPSessionState, arg: str = "") -> tuple[int, str]:
    """Handles HELP command."""
    if arg:
        cmd = arg.upper()
        help_docs = {
            "USER": "USER <username> : Specify user for authentication",
            "PASS": "PASS <password> : Specify password for authentication",
            "CWD":  "CWD <dir>      : Change working directory",
            "PWD":  "PWD            : Print working directory",
            "MKD":  "MKD <dir>      : Make directory",
            "RMD":  "RMD <dir>      : Remove directory",
            "QUIT": "QUIT           : Terminate connection",
            "HELP": "HELP [command] : Display help info"
        }
        if cmd in help_docs:
            return 214, f"214 {help_docs[cmd]}"
        else:
            return 502, f"502 Unknown command '{cmd}'."

    msg = (
        "214-The following commands are recognized:\r\n"
        " USER PASS CWD PWD MKD RMD QUIT HELP\r\n"
        "214 Help OK."
    )
    return 214, msg


def process_ftp_command(session: FTPSessionState, raw_command: str) -> tuple[int, str]:
    """
    Parses a raw command line and dispatches to the appropriate handler.
    Returns: (3_digit_code: int, response_message: str)
    """
    cmd, arg = parse_command(raw_command)
    if not cmd:
        return 500, "500 Syntax error, command unrecognized."

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
    elif cmd == "QUIT":
        return handle_quit(session)
    elif cmd == "HELP":
        return handle_help(session, arg)
    else:
        return 502, f"502 Command '{cmd}' not implemented."
