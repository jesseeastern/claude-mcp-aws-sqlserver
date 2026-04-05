"""
MCP Server — Claude <-> AWS SQL Server (VPC)
==========================================
Exposes six MCP tools that let Claude:
  * list_instances  -- enumerate all EC2 instances in the account
    * start_instance  -- boot a stopped EC2 instance
      * stop_instance   -- halt a running EC2 instance
        * run_command     -- execute a shell / PowerShell command on any EC2
                               instance via AWS Systems Manager (SSM)
                                 * sql_query       -- run a T-SQL query against SQL Server on the
                                                        Windows EC2 instance and return formatted results
                                                          * list_databases  -- convenience wrapper that lists all SQL Server DBs

                                                          Architecture
                                                          ------------
                                                            Claude Desktop --MCP--> this server (FastMCP / streamable-HTTP)
                                                                                                  |
                                                                                                                            +-- boto3 --> AWS EC2  (describe / start / stop)
                                                                                                                                                      +-- boto3 --> AWS SSM  (send-command / get-invocation)
                                                                                                                                                                                +-- pyodbc --> SQL Server on Windows EC2 (VPC-internal IP)
                                                                                                                                                                                
                                                                                                                                                                                Requirements
                                                                                                                                                                                ------------
                                                                                                                                                                                  pip install -r requirements.txt
                                                                                                                                                                                  
                                                                                                                                                                                  Configure environment variables before running:
                                                                                                                                                                                    export AWS_REGION=us-east-2
                                                                                                                                                                                      export WINDOWS_INSTANCE_ID=i-xxxxxxxxxxxxxxxxx
                                                                                                                                                                                        export SQL_SERVER_IP=10.0.0.x
                                                                                                                                                                                          export SQL_SERVER_PORT=1433
                                                                                                                                                                                            export SQL_USER=your_sql_username
                                                                                                                                                                                              export SQL_PASSWORD=your_sql_password
                                                                                                                                                                                              
                                                                                                                                                                                                python server.py
                                                                                                                                                                                                """

import logging
import os
import time

import boto3
from mcp.server.fastmcp import FastMCP

# -- Silence noisy loggers (remove in production for full visibility) -----------
logging.disable(logging.CRITICAL)

# -- MCP application ------------------------------------------------------------
app = FastMCP("vpc-mcp")

# -- Configuration (loaded from environment variables) -------------------------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
WINDOWS_INSTANCE_ID = os.environ.get("WINDOWS_INSTANCE_ID", "")
SQL_SERVER_IP = os.environ.get("SQL_SERVER_IP", "")
SQL_SERVER_PORT = int(os.environ.get("SQL_SERVER_PORT", 1433))
SQL_USER = os.environ.get("SQL_USER", "")
SQL_PASSWORD = os.environ.get("SQL_PASSWORD", "")

# -- AWS clients ----------------------------------------------------------------
ec2 = boto3.client("ec2", region_name=AWS_REGION)
ssm = boto3.client("ssm", region_name=AWS_REGION)

# -- Internal helpers ----------------------------------------------------------

def _get_platform(instance_id: str) -> str:
     """Return 'windows' or 'linux' for the given EC2 instance."""
     resp = ec2.describe_instances(InstanceIds=[instance_id])
     platform = resp["Reservations"][0]["Instances"][0].get("Platform", "linux")
     return "windows" if platform == "windows" else "linux"


def _run_ssm(instance_id: str, command: str, is_windows: bool) -> str:
     """
         Send *command* to *instance_id* via SSM and poll until completion.
             Uses AWS-RunPowerShellScript for Windows instances and
                 AWS-RunShellScript for Linux instances.
                     Polls every 5 s for up to 5 minutes before giving up.
                         """
     document = "AWS-RunPowerShellScript" if is_windows else "AWS-RunShellScript"
     response = ssm.send_command(
         InstanceIds=[instance_id],
         DocumentName=document,
         Parameters={"commands": [command]},
         TimeoutSeconds=300,
     )
     command_id = response["Command"]["CommandId"]
     for _ in range(60):  # 60 x 5 s = 5 minutes max
         time.sleep(5)
              invocation = ssm.get_command_invocation(
                  CommandId=command_id,
                  InstanceId=instance_id,
              )
              status = invocation["Status"]
              if status in ("Success", "Failed", "Cancelled", "TimedOut"):
                           stdout = invocation.get("StandardOutputContent", "")
                           stderr = invocation.get("StandardErrorContent", "")
                           return f"Status: {status}\n{stdout}\n{stderr}"
                   return "Command timed out after 5 minutes."

 # -- MCP Tools -----------------------------------------------------------------

@app.tool()
def list_instances() -> str:
     """
         List all EC2 instances in the configured AWS region.
             Returns one line per instance: Name | InstanceId | State | InstanceType | PublicIp
                 """
     resp = ec2.describe_instances()
     results = []
     for reservation in resp["Reservations"]:
              for instance in reservation["Instances"]:
                           name = next(
                                            (tag["Value"] for tag in instance.get("Tags", []) if tag["Key"] == "Name"),
                                            "unnamed",
                           )
                           public_ip = instance.get("PublicIpAddress", "none")
                           results.append(
                               f"{name} | {instance['InstanceId']} | {instance['State']['Name']} "
                               f"| {instance['InstanceType']} | {public_ip}"
                           )
                   return "\n".join(results) if results else "No instances found."


@app.tool()
def start_instance(instance_id: str) -> str:
     """
         Start a stopped EC2 instance.
             Args:
                     instance_id: The EC2 instance ID to start (e.g. i-0abc123def456789a).
                         Returns a status line with the new state and public IP address.
                             """
     ec2.start_instances(InstanceIds=[instance_id])
     time.sleep(3)  # brief pause so the state transitions
    resp = ec2.describe_instances(InstanceIds=[instance_id])
    instance = resp["Reservations"][0]["Instances"][0]
    state = instance["State"]["Name"]
    public_ip = instance.get("PublicIpAddress", "none")
    return f"Instance {instance_id} -> state: {state} | public IP: {public_ip}"


@app.tool()
def stop_instance(instance_id: str) -> str:
     """
         Stop a running EC2 instance.
             Args:
                     instance_id: The EC2 instance ID to stop (e.g. i-0abc123def456789a).
                         """
     ec2.stop_instances(InstanceIds=[instance_id])
     return f"Stop signal sent to {instance_id}."


@app.tool()
def run_command(instance_id: str, command: str) -> str:
     """
         Run an arbitrary shell command on any EC2 instance via AWS SSM.
             The correct SSM document is chosen automatically:
                   * Windows instances -> AWS-RunPowerShellScript (PowerShell)
                         * Linux instances   -> AWS-RunShellScript (bash)
                             Args:
                                     instance_id: Target EC2 instance ID.
                                             command: Command string to execute.
                                                 Returns the combined stdout/stderr and final status.
                                                     """
     is_windows = _get_platform(instance_id) == "windows"
     return _run_ssm(instance_id, command, is_windows)


@app.tool()
def sql_query(query: str, database: str = "master") -> str:
     """
         Execute a T-SQL query against SQL Server on the Windows EC2 instance.
             Connects directly to the VPC-internal IP of the Windows host using
                 pyodbc + ODBC Driver 17 for SQL Server.
                     Args:
                             query: Any valid T-SQL statement (SELECT, INSERT, EXEC, ...).
                                     database: Target database name (default: master).
                                         Returns query results as a formatted table, or a rowcount confirmation
                                             for non-SELECT statements.
                                                 """
     try:
              import pyodbc  # imported here so the server starts even without pyodbc
        connection_string = (
                     f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                     f"SERVER={SQL_SERVER_IP},{SQL_SERVER_PORT};"
                     f"DATABASE={database};"
                     f"UID={SQL_USER};"
                     f"PWD={SQL_PASSWORD};"
                     f"TrustServerCertificate=yes;"
        )
        with pyodbc.connect(connection_string, timeout=10) as conn:
                     cursor = conn.cursor()
                     cursor.execute(query)
                     if cursor.description:  # SELECT-like query
                         columns = [desc[0] for desc in cursor.description]
                                      rows = cursor.fetchall()
                                      lines = [" | ".join(columns), "-" * 60]
                                      lines += [" | ".join(str(v) for v in row) for row in rows]
                                      return "\n".join(lines)
                     else:  # DML / DDL
                         conn.commit()
                                      return f"Query executed successfully. Rows affected: {cursor.rowcount}"
except Exception as exc:
        return f"SQL Error: {exc}"


@app.tool()
def list_databases() -> str:
     """
         List all databases on the SQL Server instance.
             Returns each database's name, online/offline state, and recovery model.
                 """
    return sql_query(
             "SELECT name, state_desc, recovery_model_desc "
             "FROM sys.databases "
             "ORDER BY name;",
             database="master",
    )

# -- Entry point ---------------------------------------------------------------
if __name__ == "__main__":
     app.run(transport="streamable-http", mount_path="/mcp")
