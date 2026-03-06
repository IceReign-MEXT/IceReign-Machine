#!/usr/bin/env python3
"""
ICE REIGN MACHINE - Pre-Deployment Validator
"""
import sys, os, sqlite3
from pathlib import Path

RED, GREEN, YELLOW, BLUE, RESET = "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[0m"

def log(status, message):
    colors = {"OK": GREEN, "WARN": YELLOW, "FAIL": RED, "INFO": BLUE}
    print(f"{colors.get(status, '')}{'✅' if status=='OK' else '⚠️' if status=='WARN' else '❌' if status=='FAIL' else 'ℹ️'} {message}{RESET}")

def check_python():
    v = sys.version_info
    return log("OK", f"Python {v.major}.{v.minor}") or True if v.major == 3 and v.minor >= 8 else log("FAIL", "Need Python 3.8+")

def check_files():
    missing = [f for f in ["main.py", "requirements.txt", "Procfile", ".env"] if not Path(f).exists()]
    return log("FAIL", f"Missing: {', '.join(missing)}") if missing else log("OK", "All files present")

def check_env():
    if not Path(".env").exists(): return log("FAIL", ".env not found")
    vars = {}
    with open(".env") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                vars[k] = v
    missing = [v for v in ["BOT_TOKEN", "ADMIN_ID", "SOL_MAIN", "HELIUS_API_KEY"] if v not in vars or not vars[v]]
    if missing: return log("FAIL", f"Missing vars: {', '.join(missing)}")
    if "your_" in vars.get("BOT_TOKEN", ""): log("WARN", "BOT_TOKEN is placeholder")
    return log("OK", "Environment variables set")

def check_deps():
    failed = []
    for mod in ["flask", "telegram", "aiohttp", "aiosqlite"]:
        try: __import__(mod)
        except: failed.append(mod)
    try: __import__("solders"); log("OK", "Solders available")
    except: log("WARN", "Solders not available (OK for testing)")
    return log("FAIL", f"Missing: {', '.join(failed)}") if failed else log("OK", "Dependencies OK")

def check_procfile():
    try:
        with open("Procfile") as f: content = f.read()
        return log("OK", "Procfile valid") if "web:" in content else log("FAIL", "Invalid Procfile")
    except: return log("FAIL", "No Procfile")

def check_syntax():
    try: compile(open("main.py").read(), "main.py", "exec"); return log("OK", "Syntax valid")
    except SyntaxError as e: return log("FAIL", f"Syntax error line {e.lineno}")

def main():
    print(f"\n{BLUE}{'='*50}{RESET}")
    print(f"{BLUE}   ICE REIGN MACHINE - DEPLOYMENT CHECK{RESET}")
    print(f"{BLUE}{'='*50}{RESET}\n")
    checks = [check_python, check_files, check_env, check_deps, check_procfile, check_syntax]
    passed = sum(1 for c in checks if c())
    print(f"\n{BLUE}{'='*50}{RESET}")
    print(f"Results: {GREEN}{passed} passed{RESET}, {RED}{len(checks)-passed} failed{RESET}")
    if passed == len(checks):
        print(f"\n{GREEN}🚀 READY FOR DEPLOYMENT!{RESET}")
        print("Next: git add . && git commit -m 'v6.1' && git push")
    else:
        print(f"\n{RED}⚠️ FIX ISSUES BEFORE DEPLOYING{RESET}")
    return 0 if passed == len(checks) else 1

if __name__ == "__main__":
    sys.exit(main())
