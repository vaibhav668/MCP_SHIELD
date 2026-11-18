import time

from shield.audit import answer, pending


def main():
    print("Waiting for approval requests from MCP Shield... (Ctrl+C to quit)")
    while True:
        for request in pending():
            details = request["details"]
            print("\n--- Approval needed ---")
            print("Tool:       ", request["tool"])
            print("Inspecting: ", details["what"])
            print("Score:      ", details["score"], details["reasons"])
            print("Judge said: ", details["judge_reason"])
            print("Content:    ", details["content"])
            reply = input("Approve? [y/N] ").strip().lower()
            answer(request["thread_id"], "approve" if reply == "y" else "deny")
            print("->", "approved" if reply == "y" else "denied")
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
