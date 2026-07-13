import json
import os
import shutil

auth_path = os.path.expanduser("~/.codex/auth.json")
backup_path = os.path.expanduser("~/.codex/auth.json.bak")

def patch():
    if not os.path.exists(auth_path):
        print(f"Error: {auth_path} not found. Please log in using 'codex login' first.")
        return

    # Read current auth file
    with open(auth_path, "r") as f:
        auth_data = json.load(f)
    
    # Backup original chatgpt login session if not backed up already
    if auth_data.get("auth_mode") == "chatgpt":
        shutil.copyfile(auth_path, backup_path)
        print("[Info] ChatGPT authentication session backed up successfully.")
    
    # Load token information from the backup or the current file
    source_data = auth_data
    if os.path.exists(backup_path):
        with open(backup_path, "r") as f:
            source_data = json.load(f)
            
    tokens = source_data.get("tokens") or {}
    access_token = tokens.get("access_token")
    
    if not access_token:
        print("Error: No ChatGPT access token found. Please log in using 'codex login' first.")
        return
        
    # Convert auth mode to apikey, injecting the ChatGPT JWT access_token as the API key
    patched_data = {
        "auth_mode": "apikey",
        "OPENAI_API_KEY": access_token,
        "tokens": source_data.get("tokens"),
        "last_refresh": source_data.get("last_refresh")
    }
    
    with open(auth_path, "w") as f:
        json.dump(patched_data, f, indent=2)
        
    print("\n🎉 [Success] Successfully patched auth.json to API Key redirection mode!")
    print("Now run the following in your terminal session to start using the routing harness:\n")
    print("  export OPENAI_BASE_URL=\"http://localhost:18080/v1\"")
    print("  export CODEX_API_BASE=\"http://localhost:18080/v1\"")
    print("  export OLLAMA_HOST=\"http://127.0.0.1:18080\"")
    print("  export CODEX_OSS_PORT=18080")
    print("  codex --oss --local-provider=ollama")

if __name__ == "__main__":
    patch()
