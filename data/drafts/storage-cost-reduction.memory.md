# Storage cost reduction: memory file

Load this into the Agent's context for Storage cost reduction work. Each line is something earlier Sessions each had to find out by trial and error.

- Pass the bucket to blobctl as a bare name (e.g. kst-pod-images-prod), not an s3:// URI, or it fails with E_BADREF.
- Set STORAGE_ENV=staging before running blobctl; unset fails with E_NOENV and prod/production are denied.
