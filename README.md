# claude-mcp-aws-sqlserver

> **MCP Server** that gives Claude natural-language access to SQL Server running on a Windows EC2 instance inside an AWS VPC — no public database exposure required.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-FastMCP-blueviolet)](https://github.com/anthropics/mcp)
[![AWS](https://img.shields.io/badge/AWS-EC2%20%7C%20SSM-orange?logo=amazonaws)](https://aws.amazon.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Overview

This project demonstrates how to build an **MCP (Model Context Protocol) server** that bridges Claude Desktop to an AWS-hosted SQL Server environment. All database traffic flows over the private VPC network — the SQL Server port is never exposed to the public internet.

Claude can use plain English to:
- Inspect and manage EC2 instances (start, stop, list)
- Run PowerShell or bash commands on any instance via AWS SSM
- Query any database on the SQL Server with T-SQL
- List all databases and their health status

---

## Architecture

```
Claude Desktop
     |
     | MCP (streamable-HTTP)
     v
┌─────────────────────────────────┐
│         server.py               │
│         (FastMCP)               │
│                                 │
│  ┌──────────┐  ┌─────────────┐  │
│  │  boto3   │  │   pyodbc    │  │
│  └────┬─────┘  └──────┬──────┘  │
└───────┼───────────────┼─────────┘
        │               │
   AWS API         VPC-internal TCP
        │               │
 ┌──────┴──────┐  ┌─────┴──────────────┐
 │  EC2 + SSM  │  │  Windows EC2       │
 │  (control)  │  │  SQL Server 2019+  │
 └─────────────┘  └────────────────────┘
```

**Key design decisions:**
- SSM is used for remote command execution instead of RDP/SSH — no inbound ports needed on instances.
- Platform detection automatically selects the correct SSM document (PowerShell vs bash).
- `pyodbc` connects to SQL Server via the private VPC IP, keeping the database off the public internet.

---

## MCP Tools

| Tool | Description |
|---|---|
| `list_instances` | List all EC2 instances with state, type, and public IP |
| `start_instance` | Start a stopped EC2 instance by ID |
| `stop_instance` | Stop a running EC2 instance by ID |
| `run_command` | Run a shell or PowerShell command via SSM (auto-detects OS) |
| `sql_query` | Execute any T-SQL query against a named database |
| `list_databases` | List all SQL Server databases with state and recovery model |

---

## Prerequisites

### AWS Side
- An AWS account with at least one EC2 instance running SQL Server (Windows)
- **SSM Agent** installed and running on all managed EC2 instances
- An IAM role attached to each EC2 instance with the `AmazonSSMManagedInstanceCore` policy
- The machine running this server needs AWS credentials with permissions for `ec2:Describe*`, `ec2:StartInstances`, `ec2:StopInstances`, `ssm:SendCommand`, and `ssm:GetCommandInvocation`

### Local Machine
- Python 3.10 or later
- [ODBC Driver 17 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
  - **Windows:** Download from Microsoft
  - **macOS:** `brew install msodbcsql17`
  - **Ubuntu/Debian:** `sudo apt-get install -y msodbcsql17`
- [Claude Desktop](https://claude.ai/download) with MCP support enabled

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/jesseeastern/claude-mcp-aws-sqlserver.git
cd claude-mcp-aws-sqlserver
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure credentials

Edit `server.py` and fill in the constants at the top of the file:

```python
WINDOWS_INSTANCE_ID = "i-XXXXXXXXXXXXXXXXX"   # Your Windows EC2 instance ID
SQL_SERVER_IP       = "10.0.0.X"              # Private VPC IP of the SQL Server
SQL_SERVER_PORT     = 1433
SQL_USER            = "sa"
SQL_PASSWORD        = "your-password-here"
```

> **Tip:** For production use, load these values from environment variables or AWS Secrets Manager instead of hardcoding them.

### 4. Configure AWS credentials

The server uses the standard boto3 credential chain. The easiest approach:

```bash
aws configure
# or set environment variables:
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-2
```

### 5. Register with Claude Desktop

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vpc-mcp": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"],
      "transport": "streamable-http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### 6. Start the server

```bash
python server.py
```

---

## Example Prompts

Once connected, you can ask Claude things like:

- *"List all my EC2 instances and tell me which ones are running."*
- *"Start instance i-0abc123def456789a and wait for it to be available."*
- *"What databases exist on the SQL Server?"*
- *"Run this query against AdventureWorks2019: SELECT TOP 10 * FROM Sales.SalesOrderHeader ORDER BY TotalDue DESC"*
- *"Check free disk space on the Windows instance using PowerShell."*

---

## Security Notes

- **Never commit real passwords or AWS credentials** to source control. Use environment variables or a secrets manager.
- The placeholder values in `server.py` (`i-XXXXXXXXXXXXXXXXX`, `YOUR_SA_PASSWORD_HERE`) are intentional — replace them in your local copy only.
- Restrict the IAM role to the minimum required permissions using the principle of least privilege.
- Consider enabling AWS CloudTrail to audit all SSM command executions.

---

## Tech Stack

- **[FastMCP](https://github.com/anthropics/mcp)** — Python MCP server framework
- **[boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)** — AWS SDK for Python
- **[pyodbc](https://github.com/mkleehammer/pyodbc)** — ODBC database connectivity
- **AWS EC2** — Virtual machines in the cloud
- **AWS Systems Manager (SSM)** — Secure remote command execution without open inbound ports

---

## License

This project is licensed under the [MIT License](LICENSE).
