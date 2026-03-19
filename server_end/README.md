# EVoting Token Coordination Server

Central server that coordinates token generation across multiple Raspberry Pi devices using MongoDB and mutual TLS (mTLS).

## Architecture

```
                    ┌──────────────────────────┐
                    │     Central Server       │
                    │  Flask + MongoDB + mTLS  │
                    └────────────┬─────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
     ┌────────▼───────┐ ┌───────▼────────┐ ┌───────▼────────┐
     │  RPi Device 1  │ │  RPi Device 2  │ │  RPi Device N  │
     │  Token Gen App │ │  Token Gen App │ │  Token Gen App │
     └────────────────┘ └────────────────┘ └────────────────┘
```

Each device has its own copy of the electoral roll (for offline display) but **must request permission** from the central server before generating a token. This prevents duplicate token generation.

## Voter Status State Machine

```
not_generated ──[/request]──► requested_by_device_X
                                      │
                 ┌────────────────────┤
                 │                    │
          [/cancel]            [/confirm]
                 │                    │
                 ▼                    ▼
          not_generated      generated_at_device_X
```

## Prerequisites

1. **Python 3.10+**
2. **MongoDB 5.0+** running locally or accessible over the network
3. **TLS certificates** (see [TLS_SETUP_README.md](TLS_SETUP_README.md))

## Quick Start

### 1. Install Dependencies

```bash
cd server_end
pip install -r requirements.txt
```

### 2. Start MongoDB

```bash
# Ubuntu/Debian
sudo systemctl start mongod

# Or via Docker
docker run -d -p 27017:27017 --name evoting-mongo mongo:7
```

### 3. Import Electoral Roll

```bash
python db_init.py --csv ../Electoral_Roll.csv
# To re-import from scratch:
python db_init.py --csv ../Electoral_Roll.csv --drop
```

### 4. Set Up TLS Certificates

Follow the detailed guide in [TLS_SETUP_README.md](TLS_SETUP_README.md).

Place server certs in `server_end/certs/`:
```
certs/
├── ca.crt
├── server.crt
└── server.key
```

### 5. Start the Server

```bash
# Production (with mTLS)
python app.py

# Development (no TLS)
python app.py --no-tls
```

## API Reference

All endpoints return JSON. Base URL: `https://<server-ip>:5000` (or `http://` with `--no-tls`).

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check + DB connectivity |
| `/api/voter/<entry>` | GET | Lookup voter and current status |
| `/api/voter/<entry>/request` | POST | Claim voter for token generation |
| `/api/voter/<entry>/confirm` | POST | Confirm successful generation |
| `/api/voter/<entry>/cancel` | POST | Report failure, release lock |
| `/api/voters` | GET | Admin: list all voters |

### Example: Full Token Generation Flow

```bash
SERVER=http://localhost:5000  # or https:// with certs

# 1. Check voter status
curl $SERVER/api/voter/2022EE11737

# 2. Request permission to generate token
curl -X POST $SERVER/api/voter/2022EE11737/request \
     -H "Content-Type: application/json" \
     -d '{"device_id": "1"}'

# 3a. On SUCCESS — confirm token
curl -X POST $SERVER/api/voter/2022EE11737/confirm \
     -H "Content-Type: application/json" \
     -d '{"device_id": "1", "token_id": "uuid-here", "booth_number": "2"}'

# 3b. On FAILURE — cancel and release
curl -X POST $SERVER/api/voter/2022EE11737/cancel \
     -H "Content-Type: application/json" \
     -d '{"device_id": "1"}'
```

### With mTLS

```bash
curl --cert certs/device_1.crt \
     --key certs/device_1.key \
     --cacert certs/ca.crt \
     https://192.168.1.100:5000/api/health
```

## Testing

```bash
# 1. Import test data
python db_init.py --csv ../Electoral_Roll.csv --drop

# 2. Start server in dev mode
python app.py --no-tls

# 3. Run tests (in another terminal)
python test_api.py
```

## Configuration

All settings are in `config.py` and can be overridden via environment variables:

| Variable | Default | Description |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017/` | MongoDB connection string |
| `MONGO_DB_NAME` | `evoting` | Database name |
| `MONGO_COLLECTION` | `voters` | Collection name |
| `SERVER_HOST` | `0.0.0.0` | Bind host |
| `SERVER_PORT` | `5000` | Bind port |
| `TLS_CERT_DIR` | `./certs` | Directory for TLS certs |
| `STALE_REQUEST_TIMEOUT` | `300` | Seconds before a stale request auto-reverts |

## File Structure

```
server_end/
├── app.py               # Flask entry point with TLS
├── config.py            # Configuration constants
├── models.py            # MongoDB VoterCollection (atomic ops)
├── routes.py            # REST API endpoints
├── db_init.py           # Electoral roll CSV → MongoDB importer
├── test_api.py          # API test suite
├── requirements.txt     # Python dependencies
├── README.md            # This file
├── TLS_SETUP_README.md  # TLS certificate generation guide
└── certs/               # TLS certificates (not in git)
    ├── ca.crt
    ├── server.crt
    └── server.key
```
