import sys, os
sys.path.insert(0, '.')
os.chdir('C:/Users/arthu/Coding/Firma')

import tempfile, asyncio
from engine.transport.pi_mesh_transport import PiMeshTransport

CREWS = {
    'PLANNER': 'pimesh/planning-crew',
    'CODER': 'pimesh/coding-crew',
    'REVIEWER': 'pimesh/reviewing-crew',
    'RESEARCHER': 'pimesh/planning-crew',  # Researcher uses planning-crew dir
}

def test():
    root = tempfile.mkdtemp()
    t = PiMeshTransport(crew_cwds=CREWS, project_root=root)
    roles = [
        ('PLANNER', CREWS['PLANNER']),
        ('RESEARCHER', CREWS['PLANNER']),  # researcher uses planning-crew dir
        ('CODER', CREWS['CODER']),
        ('REVIEWER', CREWS['REVIEWER']),
    ]

    legacy_phrase = "Schreibe SOFORT eine Datei namens `worker_response.{task_id}.response.json`"

    for role, crew_dir in roles:
        payload = {
            'event': 'TASK_ASSIGNMENT',
            'run_id': 'run-X',
            'task_id': 'task-1',
            'role': role,
            'state_revision': 5,
            'prompt': 'make website',
            'task_definition': {
                'description': f'{role} task',
                'expected_artifacts': [{'path': 'index.html', 'type': 'CREATE'}],
                'acceptance_criteria': ['EXISTS:index.html'],
            },
        }
        asyncio.run(t.dispatch(payload))
        md = open(os.path.join(root, crew_dir, '.pi', 'messenger', 'crew', 'tasks', 'task-1.md'), encoding='utf-8').read()

        print(f'\n=== {role} ===')
        print(f'OUTPUT CONTRACT ({role}) in md:', f'OUTPUT CONTRACT ({role})' in md)
        print(f'Count:', md.count(f'OUTPUT CONTRACT ({role})'))
        
        for other_role, _ in roles:
            if other_role == role:
                continue
            count = md.count(f'OUTPUT CONTRACT ({other_role})')
            if count > 0:
                print(f'ERROR: OUTPUT CONTRACT ({other_role}) found {count} times in {role} md!')

        print(f'Legacy phrase in md:', legacy_phrase in md)

        # Assertions
        assert f'OUTPUT CONTRACT ({role})' in md
        assert md.count(f'OUTPUT CONTRACT ({role})') == 1
        for other_role, _ in roles:
            if other_role == role:
                continue
            assert f'OUTPUT CONTRACT ({other_role})' not in md
        assert legacy_phrase not in md
        print(f'PASS: {role}')

    print('ALL PASSED')

test()
