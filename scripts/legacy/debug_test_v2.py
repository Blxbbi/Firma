from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from engine.models import Base, Plan, Task, Artifact
from engine.repository import MessageRepository
from engine.workflow import process_task_message
from engine.models import Message, MessageHeader, MessageType
import os
import tempfile
from pathlib import Path

# Setup
db_file = "debug_test.db"
if os.path.exists(db_file): os.remove(db_file)
engine = create_engine(f"sqlite:///{db_file}")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

repo = MessageRepository(session)
plan_id = "p1"
task_id = "t1"
plan = Plan(id=plan_id, name="p1", status="PLANNED")
session.add(plan)
task = Task(id=task_id, plan_id=plan_id, state="IN_PROGRESS", expected_artifacts=[], acceptance_criteria=[])
session.add(task)
session.commit()

# Temp dir for artifacts
temp_dir = tempfile.TemporaryDirectory()
os.environ["FIRMA_ARTIFACT_STORE_DIR"] = temp_dir.name

# First Result
msg1 = Message(
    header=MessageHeader(sender="w1", recipient="e", message_type=MessageType.TASK_RESULT, plan_id=plan_id),
    payload={"artifacts": [{"path": "main.py", "content": "v1", "action": "CREATE"}]}
)
print("Calling process_task_message 1...")
process_task_message(session, msg1, task_id, MessageType.TASK_RESULT)
print(f"DB Count after 1: {session.query(Artifact).count()}")

# Second Result
msg2 = Message(
    header=MessageHeader(sender="w1", recipient="e", message_type=MessageType.TASK_RESULT, plan_id=plan_id),
    payload={"artifacts": [{"path": "main.py", "content": "v2", "action": "UPDATE"}]}
)
print("Calling process_task_message 2...")
process_task_message(session, msg2, task_id, MessageType.TASK_RESULT)
print(f"DB Count after 2: {session.query(Artifact).count()}")

art = session.query(Artifact).first()
print(f"Final version: {art.version if art else 'None'}")
temp_dir.cleanup()
