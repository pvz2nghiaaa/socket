import threading
import time
import socket

lock = threading.Lock()
listThread = []
shutdown_event = threading.Event()

def close_inactive_thread():
    global listThread
    with lock:
        listThread = [thread for thread in listThread if thread.is_alive()]
            

def create_thread(client_socket, client_addr, task_function):
    close_inactive_thread()
    
    new_thread = threading.Thread(
        target=task_function,
        args=(client_socket, client_addr, shutdown_event)
    )
    new_thread.start()

    with lock: 
        listThread.append(new_thread)
        active_count = len(listThread)
    print(f"[Server] New thread created ({new_thread.name}): {active_count} active threads total.")

def shutdown_monitor(server_socket):
    print("[Server] Shuting down server...")
    shutdown_event.set()

    # just in case a thread is removed or inserted suddenly during iteration
    with lock:
        safe_threads = list(listThread)
    
    for thread in safe_threads:
        if thread.is_alive():
            print(f"[Server] Waiting for thread {thread.name} to finish.")
            thread.join()
            
    print("[Server] All clients have disconnected.")
    server_socket.close()

def ftp_task_function(client_socket, client_addr, shutdown_signal):
    # thời gian chờ tối đa 300s
    client_socket.settimeout(300.0)
    
    while not shutdown_signal.is_set():
        try:
            data = client_socket.recv(1024)
            if not data:
                break
                
        except socket.timeout:
            # zombie detection
            print(f"[!] Timeout: Client {client_addr} is hung. Close this thread!")
            break
            
        except ConnectionResetError:
            print(f"[!] Connection Reset: Suddenly lost connection from {client_addr}.")
            break

    client_socket.close()
