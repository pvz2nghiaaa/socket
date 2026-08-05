import socket
import sys


class HybridFTPClientCLI:
    def __init__(self, default_host='127.0.0.1', default_port=2121):
        self.default_host = default_host
        self.default_port = default_port
        self.client_socket = None
        self.is_connected = False
        self.server_host = None
        self.server_port = None

    def connect_server(self, host=None, port=None):
        """Connects to the TCP FTP server."""
        if self.is_connected:
            print("[Client] Already connected to server. Disconnect first.")
            return

        target_host = host if host else self.default_host
        target_port = int(port) if port else self.default_port

        try:
            print(f"[Client] Connecting to {target_host}:{target_port}...")
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(5.0)  # Timeout for connect and send/recv
            self.client_socket.connect((target_host, target_port))

            self.is_connected = True
            self.server_host = target_host
            self.server_port = target_port
            print(f"[Client] Connected successfully to server at {target_host}:{target_port}")
        except Exception as e:
            print(f"[Client Error] Failed to connect: {e}")
            self.disconnect_server()

    def send_message(self, message):
        """Sends data/message to the connected server."""
        if not self.is_connected or not self.client_socket:
            print("[Client] Not connected to any server. Use 'connect' command first.")
            return

        try:
            payload = message.encode('utf-8')
            self.client_socket.sendall(payload)
            print(f"[Client] Sent ({len(payload)} bytes): {message}")

            # Attempt to receive response from server if available
            try:
                response = self.client_socket.recv(1024)
                if response:
                    print(f"[Server Response]: {response.decode('utf-8', errors='ignore')}")
                else:
                    print("[Client] Server closed the connection.")
                    self.disconnect_server()
            except socket.timeout:
                print("[Client] No immediate response from server (timeout).")
        except Exception as e:
            print(f"[Client Error] Error sending data: {e}")
            self.disconnect_server()

    def display_state(self):
        """Displays current client network and connection state."""
        print("\n--- Client State ---")
        print(f"Status:      {'CONNECTED' if self.is_connected else 'DISCONNECTED'}")
        if self.is_connected:
            print(f"Server IP:   {self.server_host}")
            print(f"Server Port: {self.server_port}")
        else:
            print(f"Default IP:  {self.default_host}")
            print(f"Default Port:{self.default_port}")

    def disconnect_server(self):
        """Closes the current socket connection."""
        if self.client_socket:
            try:
                self.client_socket.close()
            except Exception:
                pass
            self.client_socket = None

        if self.is_connected:
            print("[Client] Disconnected from server.")
        self.is_connected = False
        self.server_host = None
        self.server_port = None

    def start_loop(self):
        """Main interactive CLI loop."""
        print("==============================================")
        print("      Hybrid FTP Client Interactive CLI       ")
        print("==============================================")
        print("Commands: connect [host] [port] | send <msg> | state | disconnect | help | exit\n")

        while True:
            try:
                status = "CONNECTED" if self.is_connected else "DISCONNECTED"
                user_input = input(f"[{status}]> ").strip()

                if not user_input:
                    continue

                parts = user_input.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""

                if cmd == 'connect':
                    host = self.default_host
                    port = self.default_port
                    if arg:
                        tokens = arg.split()
                        if len(tokens) >= 1:
                            host = tokens[0]
                        if len(tokens) >= 2:
                            port = tokens[1]
                    self.connect_server(host, port)

                elif cmd == 'send':
                    if not arg:
                        print("Usage: send <message>")
                    else:
                        self.send_message(arg)

                elif cmd in ('state', 'status'):
                    self.display_state()

                elif cmd in ('disconnect', 'close'):
                    self.disconnect_server()

                elif cmd == 'help':
                    print("\nCLI Commands:")
                    print("  connect [host] [port]  - Connect to server (default 127.0.0.1 2121)")
                    print("  send <message>         - Send a message to server")
                    print("  state / status         - Display client connection status")
                    print("  disconnect / close     - Close active connection")
                    print("  help                   - Display this help menu")
                    print("  exit / quit            - Disconnect and exit client CLI")

                elif cmd in ('exit', 'quit'):
                    self.disconnect_server()
                    print("Exiting CLI application.")
                    break

                else:
                    print(f"Unknown command: '{cmd}'. Type 'help' for options.")

            except (KeyboardInterrupt, EOFError):
                print("\nKeyboard interrupt detected.")
                self.disconnect_server()
                break


if __name__ == "__main__":
    cli = HybridFTPClientCLI()
    cli.start_loop()
