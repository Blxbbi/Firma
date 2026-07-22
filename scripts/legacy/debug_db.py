from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from engine.models import Base, Plan, Task, Artifact
import uuid

engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

plan = Plan(id="p1", name="p1", status="PLANNED")
session.add(plan)
task = Task(id="t1", plan_id="p1", state="READY", expected_artifacts=[], acceptance_criteria=[])
session.add(task)
session.commit()

print("Saving artifact...")
art = Artifact(task_id="t1", path="main.py", hash="h1", storage_path="s1")
session.add(art)
session.commit()

print(f"Count: {session.query(Artifact).count()}")
art_found = session.query(Artifact).filter_by(task_id="t1", path="main.py").first()
print(f"Found: {art_found}")
