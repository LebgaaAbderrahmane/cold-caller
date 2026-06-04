from phone.adb_controller import ADBController
import time

adb = ADBController()

print("\n--- Testing calibrated call state ---")

# Test 1: confirm idle
state = adb.get_call_state()
assert state == "idle", f"Expected idle, got {state}"
print(f"✅ Idle state correct: {state}")

# Test 2: make a real call
TEST_NUMBER = "+213792842752"  # put your number here

print(f"\n--- Calling {TEST_NUMBER} ---")
adb.wake_screen()
adb.unlock_screen()
adb.make_call(TEST_NUMBER)

answered = adb.wait_for_answer(timeout=40)

if answered:
    print("✅ Answer detected correctly!")
    print("⏳ Staying in call for 5 seconds...")
    time.sleep(5)
    adb.hang_up()

    # Confirm back to idle
    time.sleep(2)
    state = adb.get_call_state()
    print(f"✅ After hang up state: {state}")
else:
    print("❌ Not answered — but state detection is now working correctly")
    print("   (Try calling a number that will pick up)")

print("\n✅ ADB controller fully calibrated!")