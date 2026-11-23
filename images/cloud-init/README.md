# cloud-init

The images boot without any seed: first boot generates a one-time admin password and prints the
settings URL on the console. To customise a VM (hostname, extra SSH key), attach a NoCloud seed ISO:

```bash
./make-seed.sh -o seed.iso -n devenv -k ~/.ssh/id_ed25519.pub
```

On Windows, `deploy/windows/New-DevEnvVM.ps1 -SshPublicKey ...` builds the seed for you.
