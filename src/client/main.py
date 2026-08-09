import os
import sys
import socket
import select

# Add parent directory of 'src' to path so we can do relative/absolute imports cleanly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.protocol.rdt import RDTSender, RDTReceiver

class HybridFTPClientCLI:
    def __init__(self, default_host='127.0.0.1', default_port=2121):
        self.default_host = default_host
        self.default_port = default_port
        self.control_socket = None
        self.is_connected = False
        self.server_host = None
        self.server_port = None
        
        # Connection options
        self.data_mode = "PASV"        # PASV or PORT
        self.transfer_type = "I"       # I (Binary) or A (ASCII)
        self.transfer_mode = "S"       # S (Stream)
        
    def read_control_response(self) -> str:
        """Reads control response from the server, supporting multi-line outputs."""
        if not self.control_socket:
            return ""
            
        response = ""
        while True:
            chunk = self.control_socket.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed connection.")
            response += chunk.decode('utf-8', errors='ignore')
            if response.endswith("\r\n"):
                lines = response.split("\r\n")
                last_line = lines[-2] if len(lines) >= 2 else lines[0]
                first_line = lines[0]
                
                # Check for RFC 959 multi-line format: starts with 'XYZ-' and ends with 'XYZ '
                if len(first_line) >= 4 and first_line[3] == '-':
                    code = first_line[:3]
                    ended = False
                    for line in reversed(lines[:-1]):
                        if line.startswith(code + " "):
                            ended = True
                            break
                    if ended:
                        break
                else:
                    break
        return response

    def connect_server(self, host=None, port=None):
        if self.is_connected:
            print("[Client] Already connected. Please disconnect first.")
            return

        target_host = host if host else self.default_host
        target_port = int(port) if port else self.default_port

        try:
            print(f"[Client] Connecting to {target_host}:{target_port}...")
            self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.control_socket.settimeout(10.0)
            self.control_socket.connect((target_host, target_port))

            self.is_connected = True
            self.server_host = target_host
            self.server_port = target_port
            
            # Read server greeting
            greeting = self.read_control_response()
            print(greeting.strip())
        except Exception as e:
            print(f"[Client Error] Connection failed: {e}")
            self.disconnect_server()

    def disconnect_server(self):
        if self.control_socket:
            try:
                self.control_socket.sendall(b"QUIT\r\n")
                resp = self.read_control_response()
                print(resp.strip())
            except Exception:
                pass
            try:
                self.control_socket.close()
            except Exception:
                pass
            self.control_socket = None

        if self.is_connected:
            print("[Client] Disconnected from server.")
        self.is_connected = False
        self.server_host = None
        self.server_port = None

    def setup_data_channel(self) -> tuple[socket.socket, tuple]:
        """
        Creates and registers the client data socket based on Active/Passive settings.
        Returns (data_socket, server_address).
        """
        if not self.is_connected:
            print("[Client Error] Not connected to server.")
            return None, None

        if self.data_mode == "PASV":
            self.control_socket.sendall(b"PASV\r\n")
            resp = self.read_control_response()
            print(resp.strip())
            if not resp.startswith("227"):
                print("[Client Error] Failed to enter Passive Mode.")
                return None, None

            try:
                start = resp.find("(")
                end = resp.find(")")
                parts = resp[start+1:end].split(",")
                ip = ".".join(parts[:4])
                port = int(parts[4]) * 256 + int(parts[5])
                server_addr = (ip, port)
                
                # Open client UDP socket and send handshake
                data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                data_socket.sendto(b"HANDSHAKE", server_addr)
                return data_socket, server_addr
            except Exception as e:
                print(f"[Client Error] PASV parsing error: {e}")
                return None, None

        else: # ACTIVE mode (PORT)
            try:
                data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                client_ip = self.control_socket.getsockname()[0]
                data_socket.bind((client_ip, 0))
                bound_ip, bound_port = data_socket.getsockname()
            except Exception as e:
                print(f"[Client Error] Failed to bind local active data socket: {e}")
                return None, None

            try:
                h1, h2, h3, h4 = bound_ip.split(".")
                p1 = bound_port // 256
                p2 = bound_port % 256
                cmd = f"PORT {h1},{h2},{h3},{h4},{p1},{p2}"
                self.control_socket.sendall((cmd + "\r\n").encode('utf-8'))
                resp = self.read_control_response()
                print(resp.strip())
                if not resp.startswith("200"):
                    print("[Client Error] PORT request rejected.")
                    data_socket.close()
                    return None, None
                return data_socket, None
            except Exception as e:
                print(f"[Client Error] PORT command setup failed: {e}")
                data_socket.close()
                return None, None

    def execute_list(self, arg=""):
        data_socket, server_addr = self.setup_data_channel()
        if not data_socket:
            return

        resp1_received = False
        try:
            cmd = f"LIST {arg}".strip()
            self.control_socket.sendall((cmd + "\r\n").encode('utf-8'))
            resp1 = self.read_control_response()
            print(resp1.strip())
            if not resp1.startswith("150"):
                data_socket.close()
                return
            resp1_received = True

            temp_path = "temp_list_output.txt"
            receiver = RDTReceiver(data_socket)
            success = receiver.receive_file(temp_path, file_mode='wb', transfer_type='A')
            
            if success and os.path.exists(temp_path):
                with open(temp_path, 'r', encoding='utf-8', errors='ignore') as f:
                    print(f.read().strip())
                os.remove(temp_path)
        except Exception as e:
            print(f"[Client Error] LIST execution failed: {e}")
        finally:
            data_socket.close()
            if resp1_received:
                try:
                    resp2 = self.read_control_response()
                    print(resp2.strip())
                except Exception:
                    pass

    def execute_nlst(self, arg=""):
        data_socket, server_addr = self.setup_data_channel()
        if not data_socket:
            return

        resp1_received = False
        try:
            cmd = f"NLST {arg}".strip()
            self.control_socket.sendall((cmd + "\r\n").encode('utf-8'))
            resp1 = self.read_control_response()
            print(resp1.strip())
            if not resp1.startswith("150"):
                data_socket.close()
                return
            resp1_received = True

            temp_path = "temp_nlst_output.txt"
            receiver = RDTReceiver(data_socket)
            success = receiver.receive_file(temp_path, file_mode='wb', transfer_type='A')
            
            if success and os.path.exists(temp_path):
                with open(temp_path, 'r', encoding='utf-8', errors='ignore') as f:
                    print(f.read().strip())
                os.remove(temp_path)
        except Exception as e:
            print(f"[Client Error] NLST execution failed: {e}")
        finally:
            data_socket.close()
            if resp1_received:
                try:
                    resp2 = self.read_control_response()
                    print(resp2.strip())
                except Exception:
                    pass

    def execute_get(self, remote_file, local_file=None):
        if not local_file:
            local_file = os.path.basename(remote_file)

        data_socket, server_addr = self.setup_data_channel()
        if not data_socket:
            return

        resp1_received = False
        try:
            cmd = f"RETR {remote_file}"
            self.control_socket.sendall((cmd + "\r\n").encode('utf-8'))
            resp1 = self.read_control_response()
            print(resp1.strip())
            if not resp1.startswith("150"):
                data_socket.close()
                return
            resp1_received = True

            print(f"[Client] Commencing RDT file download to '{local_file}'...")
            receiver = RDTReceiver(data_socket)
            
            try:
                success = receiver.receive_file(local_file, file_mode='wb', control_socket=None, transfer_type=self.transfer_type)
            except KeyboardInterrupt:
                print("\n[Client] Sending ABOR to cancel active transfer...")
                self.control_socket.sendall(b"ABOR\r\n")
                print(self.read_control_response().strip())
                print(self.read_control_response().strip())
                success = False
                resp1_received = False

            if success:
                print("[Client] Download completed successfully.")
            else:
                print("[Client Error] Download aborted.")
        except Exception as e:
            print(f"[Client Error] RETR failed: {e}")
        finally:
            data_socket.close()
            if resp1_received:
                try:
                    resp2 = self.read_control_response()
                    print(resp2.strip())
                except Exception:
                    pass

    def execute_put(self, local_file, remote_file=None, append=False, unique=False):
        if not os.path.exists(local_file):
            print(f"[Client Error] Local file '{local_file}' not found.")
            return

        if not remote_file:
            remote_file = os.path.basename(local_file)

        data_socket, server_addr = self.setup_data_channel()
        if not data_socket:
            return

        # For Active mode upload, wait for Active handshake from server
        if self.data_mode == "PORT" and not server_addr:
            print("[Client] Awaiting active handshake from server...")
            data_socket.settimeout(5.0)
            try:
                data, addr = data_socket.recvfrom(1024)
                if data == b"HANDSHAKE":
                    server_addr = addr
                    print(f"[Client] Active server port resolved: {server_addr}")
            except socket.timeout:
                print("[Client Error] Handshake timeout from server. Aborting.")
                data_socket.close()
                return

        resp1_received = False
        try:
            if unique:
                cmd = "STOU"
            elif append:
                cmd = f"APPE {remote_file}"
            else:
                cmd = f"STOR {remote_file}"

            self.control_socket.sendall((cmd + "\r\n").encode('utf-8'))
            resp1 = self.read_control_response()
            print(resp1.strip())
            if not resp1.startswith("150") and not resp1.startswith("250"):
                data_socket.close()
                return
            resp1_received = True

            print(f"[Client] Commencing RDT file upload for '{local_file}'...")
            sender = RDTSender(data_socket, server_addr)
            
            try:
                success = sender.send_file(local_file, control_socket=None, transfer_type=self.transfer_type)
            except KeyboardInterrupt:
                print("\n[Client] Sending ABOR to abort active transfer...")
                self.control_socket.sendall(b"ABOR\r\n")
                print(self.read_control_response().strip())
                print(self.read_control_response().strip())
                success = False
                resp1_received = False

            if success:
                print("[Client] Upload completed successfully.")
            else:
                print("[Client Error] Upload aborted.")
        except Exception as e:
            print(f"[Client Error] Upload command execution failed: {e}")
        finally:
            data_socket.close()
            if resp1_received:
                try:
                    resp2 = self.read_control_response()
                    print(resp2.strip())
                except Exception:
                    pass

    def send_raw_command(self, cmd_line):
        if not self.is_connected:
            print("[Client] Not connected. Use 'connect' command first.")
            return

        try:
            self.control_socket.sendall((cmd_line + "\r\n").encode('utf-8'))
            resp = self.read_control_response()
            print(resp.strip())
        except Exception as e:
            print(f"[Client Error] Control channel command error: {e}")
            self.disconnect_server()

    def display_state(self):
        print("\n--- Hybrid FTP Client CLI State ---")
        print(f"Connection Status: {'CONNECTED' if self.is_connected else 'DISCONNECTED'}")
        if self.is_connected:
            print(f"Remote Server:     {self.server_host}:{self.server_port}")
        print(f"Data Channel Mode: {self.data_mode}")
        print(f"Transfer Type:     {self.transfer_type} ({'ASCII' if self.transfer_type == 'A' else 'Binary'})")
        print(f"Transfer Mode:     {self.transfer_mode} (Stream)")
        print("-" * 35)

    def start_loop(self):
        print("==================================================")
        print("        Hybrid FTP Client Interactive CLI         ")
        print("==================================================")
        print("Type 'help' to view the list of available commands.\n")

        while True:
            try:
                status = "CONNECTED" if self.is_connected else "DISCONNECTED"
                user_input = input(f"[{status}]> ").strip()

                if not user_input:
                    continue

                parts = user_input.split(maxsplit=2)
                cmd = parts[0].lower()
                
                # Check connected state for commands requiring connection
                if cmd not in ('connect', 'state', 'status', 'help', 'exit', 'quit') and not self.is_connected:
                    print("[Client Error] Not connected. Connect to the server first.")
                    continue

                if cmd == 'connect':
                    host = self.default_host
                    port = self.default_port
                    if len(parts) > 1:
                        tokens = parts[1].split()
                        if len(tokens) >= 1:
                            host = tokens[0]
                        if len(tokens) >= 2:
                            port = tokens[1]
                    self.connect_server(host, port)

                elif cmd in ('login', 'auth'):
                    user = input("Username: ").strip()
                    password = input("Password: ").strip()
                    self.send_raw_command(f"USER {user}")
                    self.send_raw_command(f"PASS {password}")

                elif cmd in ('passive', 'pasv'):
                    self.data_mode = "PASV"
                    print("[Client] Data connection mode set to PASSIVE.")

                elif cmd in ('active', 'port'):
                    self.data_mode = "PORT"
                    print("[Client] Data connection mode set to ACTIVE.")

                elif cmd == 'type':
                    if len(parts) < 2:
                        print("Usage: type <A|I>")
                    else:
                        t = parts[1].upper()
                        if t in ("A", "I"):
                            self.transfer_type = t
                            self.send_raw_command(f"TYPE {t}")
                        else:
                            print("[Client Error] Invalid type. Supported types: A, I.")

                elif cmd == 'mode':
                    if len(parts) < 2:
                        print("Usage: mode <S|B|C>")
                    else:
                        m = parts[1].upper()
                        if m in ("S", "B", "C"):
                            self.transfer_mode = m
                            self.send_raw_command(f"MODE {m}")
                        else:
                            print("[Client Error] Invalid mode. Supported modes: S, B, C.")

                elif cmd in ('ls', 'list'):
                    arg = parts[1] if len(parts) > 1 else ""
                    self.execute_list(arg)

                elif cmd == 'nlst':
                    arg = parts[1] if len(parts) > 1 else ""
                    self.execute_nlst(arg)

                elif cmd == 'get':
                    if len(parts) < 2:
                        print("Usage: get <remote_file> [local_file]")
                    else:
                        tokens = parts[1].split()
                        remote = tokens[0]
                        local = tokens[1] if len(tokens) > 1 else None
                        self.execute_get(remote, local)

                elif cmd == 'put':
                    if len(parts) < 2:
                        print("Usage: put <local_file> [remote_file]")
                    else:
                        tokens = parts[1].split()
                        local = tokens[0]
                        remote = tokens[1] if len(tokens) > 1 else None
                        self.execute_put(local, remote, append=False, unique=False)

                elif cmd == 'append':
                    if len(parts) < 2:
                        print("Usage: append <local_file> <remote_file>")
                    else:
                        tokens = parts[1].split()
                        if len(tokens) < 2:
                            print("Usage: append <local_file> <remote_file>")
                        else:
                            self.execute_put(tokens[0], tokens[1], append=True, unique=False)

                elif cmd == 'stou':
                    if len(parts) < 2:
                        print("Usage: stou <local_file>")
                    else:
                        self.execute_put(parts[1].strip(), append=False, unique=True)

                elif cmd == 'cwd':
                    if len(parts) < 2:
                        print("Usage: cwd <directory>")
                    else:
                        self.send_raw_command(f"CWD {parts[1]}")

                elif cmd == 'cdup':
                    self.send_raw_command("CDUP")

                elif cmd == 'pwd':
                    self.send_raw_command("PWD")

                elif cmd == 'mkdir':
                    if len(parts) < 2:
                        print("Usage: mkdir <directory>")
                    else:
                        self.send_raw_command(f"MKD {parts[1]}")

                elif cmd == 'rmdir':
                    if len(parts) < 2:
                        print("Usage: rmdir <directory>")
                    else:
                        self.send_raw_command(f"RMD {parts[1]}")

                elif cmd == 'delete':
                    if len(parts) < 2:
                        print("Usage: delete <file>")
                    else:
                        self.send_raw_command(f"DELE {parts[1]}")

                elif cmd == 'rename':
                    if len(parts) < 2:
                        print("Usage: rename <old_name> <new_name>")
                    else:
                        tokens = parts[1].split()
                        if len(tokens) < 2:
                            print("Usage: rename <old_name> <new_name>")
                        else:
                            self.send_raw_command(f"RNFR {tokens[0]}")
                            self.send_raw_command(f"RNTO {tokens[1]}")

                elif cmd == 'hash':
                    if len(parts) < 2:
                        print("Usage: hash <filename> [MD5|SHA-256]")
                    else:
                        algo = parts[2] if len(parts) > 2 else "MD5"
                        self.send_raw_command(f"HASH {parts[1]} {algo}")

                elif cmd in ('state', 'status'):
                    self.display_state()

                elif cmd == 'disconnect':
                    self.disconnect_server()

                elif cmd == 'help':
                    print("\nHybrid FTP Client Commands:")
                    print("  connect [host] [port]           - Connect to FTP Server control channel")
                    print("  login                           - Prompt for login credentials")
                    print("  passive / pasv                  - Toggle passive data mode (Default)")
                    print("  active / port                   - Toggle active data mode")
                    print("  type <A|I>                      - Set ASCII or Binary transfer representation")
                    print("  mode <S|B|C>                    - Set stream, block, or compressed mode")
                    print("  ls / list [path]                - Detailed directory listing over RDT")
                    print("  nlst [path]                     - Name-only directory listing over RDT")
                    print("  get <remote_file> [local_file]  - Download file from server")
                    print("  put <local_file> [remote_file]  - Upload file to server")
                    print("  append <local_file> <rem_file>  - Append local file contents to server file")
                    print("  stou <local_file>               - Unique upload file")
                    print("  pwd                             - Print working directory on server")
                    print("  cwd <directory>                 - Change working directory on server")
                    print("  cdup                            - Change working directory to parent")
                    print("  mkdir <directory>               - Create directory on server")
                    print("  rmdir <directory>               - Remove directory on server")
                    print("  delete <file>                   - Delete file on server")
                    print("  rename <old> <new>              - Rename file on server")
                    print("  hash <file> [algo]              - Query file hash (MD5/SHA-256)")
                    print("  state / status                  - Print local CLI connection parameters")
                    print("  disconnect                      - Gracefully disconnect from server")
                    print("  exit / quit                     - Disconnect and exit client CLI\n")
                    print("Note: You can also type raw custom FTP commands (e.g. HELP, NOOP, STAT) directly.")

                elif cmd in ('exit', 'quit'):
                    self.disconnect_server()
                    print("Exiting CLI application.")
                    break

                else:
                    # Treat anything else as a raw FTP command sent directly to the control channel
                    self.send_raw_command(user_input)

            except (KeyboardInterrupt, EOFError):
                print("\n[Client] Interrupted. Disconnecting.")
                self.disconnect_server()
                break

if __name__ == "__main__":
    cli = HybridFTPClientCLI()
    cli.start_loop()
