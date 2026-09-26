# Storage cost reduction: memory file

Load this into the Agent's context for Storage cost reduction work. Each line is something earlier Sessions each had to find out by trial and error.

- Pass the bare bucket name to --bucket for blobctl (including plan and apply); the s3:// URI form is rejected with E_BADREF.
- Set STORAGE_ENV=staging before running blobctl; unset STORAGE_ENV fails with E_NOENV; only staging is permitted to this credential; prod/production are denied; stage/dev/test are unknown environments.
