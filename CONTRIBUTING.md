# Contributing

Thanks for improving OpenCode Pet. Please open an issue before large changes so we can agree on behavior and supported platforms. Bug reports should include your OpenCode version, Linux desktop environment, reproduction steps, and any error shown by the pet (remove private paths or prompts before posting).

Run the checks before opening a pull request:

```bash
python3 -m unittest -v test_pet.py
bun test plugin.test.ts
```

Keep the plugin's loopback relay limited to the operations the UI needs. Do not add credentials, conversations, exported pets or other personal files to Git. Custom pet art belongs to its creator; obtain permission before contributing art assets. Code contributions are submitted under the repository's MIT license.
