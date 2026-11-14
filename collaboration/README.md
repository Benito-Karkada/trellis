# Local course snapshot

This private snapshot contains the development course database and private course
assets. It excludes students, workspaces, submissions, progress, quiz attempts,
execution jobs, and browser sessions.

After cloning the repository:

1. Put the shared `.env` file in the repository root.
2. Start Docker Desktop.
3. From the repository root, extract and restore the snapshot:

   ```bash
   tar -xzf collaboration/cs1301-course-snapshot.tar.gz -C collaboration
   collaboration/collaborator-snapshot-20260909/restore.sh
   ```

4. Open <http://localhost:5173> and choose **Open local workspace**.

Django superuser access is not required. Restoring replaces the local `cs1301`
Docker database on that computer.
