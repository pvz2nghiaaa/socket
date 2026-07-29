import struct
import hashlib

# ! : Network (Big-Endian)
# I : unsigned int (4 bytes) - Seq No
# I : unsigned int (4 bytes) - Ack No
# H : unsigned short (2 bytes) - Checksum
# B : unsigned char (1 byte) - Flags
# H : unsigned short (2 bytes) - Payload Length
HEADER_FORMAT = '!IIHBH'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

FLAG_SYN = 0x01
FLAG_ACK = 0x02
FLAG_FIN = 0x04
FLAG_DATA = 0x08

def calculate_checksum(data: bytes) -> int:
    hash_obj = hashlib.md5(data)
    return struct.unpack('!H', hash_obj.digest()[:2])[0]

def create_packet(seq_no, ack_no, flags, payload: bytes = b"") -> bytes:
    payload_len = len(payload)
    # Cần pack 2 lần: Lần 1 gán tạm checksum để lấy dữ liệu tính hash
	# lần 2 chèn checksum thật vào header
    temp_header = struct.pack(HEADER_FORMAT, seq_no, ack_no, 0, flags, payload_len)
    packet_checksum = calculate_checksum(temp_header + payload)
    real_header = struct.pack(HEADER_FORMAT, seq_no, ack_no, packet_checksum, flags, payload_len)
    
    return real_header + payload

def parse_packet(packet: bytes):
    if len(packet) < HEADER_SIZE:
        raise ValueError("Packet is too small to contain a valid header.")
        
    header_bytes = packet[:HEADER_SIZE]
    payload = packet[HEADER_SIZE:]
    
    seq_no, ack_no, received_checksum, flags, payload_len = struct.unpack(HEADER_FORMAT, header_bytes)
    
    temp_header = struct.pack(HEADER_FORMAT, seq_no, ack_no, 0, flags, payload_len)
    expected_checksum = calculate_checksum(temp_header + payload)
    
    is_corrupted = (received_checksum != expected_checksum)
    
    return {
        "seq_no": seq_no,
        "ack_no": ack_no,
        "flags": flags,
        "payload_length": payload_len,
        "payload": payload,
        "is_corrupted": is_corrupted
    }