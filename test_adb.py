from phone.adb_controller import ADBController
from config import SIM_SLOT
import time
import os

adb = ADBController()

print(f"\n--- ADB Controller Test ---")
print(f"SIM slot configured: {SIM_SLOT}")

# Test 1: confirm idle
state = adb.get_call_state()
assert state == "idle", f"Expected idle, got {state}"
print(f"Idle state correct: {state}")

# Test 2: subscription info
print("\n--- SIM / Subscription Info ---")
sub_id = adb._get_subscription_id_for_slot(SIM_SLOT)
print(f"Subscription ID for slot {SIM_SLOT}: {sub_id}")

setting_before = adb._get_voice_call_setting()
print(f"Current voice SIM setting: {setting_before}")

# Test 3: SIM prepare + restore
print("\n--- SIM prepare/restore test ---")
adb.prepare_sim()
time.sleep(1)
adb._restore_voice_call_setting()

# Test 4: make a real call
TEST_NUMBER = os.getenv("TEST_PHONE_NUMBER", "+213792842752")
print(f"\n--- Calling {TEST_NUMBER} (SIM slot {SIM_SLOT}) ---")
adb.make_call(TEST_NUMBER)

answered = adb.wait_for_answer(timeout=40)

if answered:
    print("Answer detected correctly!")
    print("Staying in call for 5 seconds...")
    time.sleep(5)
    adb.hang_up()
    time.sleep(2)
    state = adb.get_call_state()
    print(f"After hang up state: {state}")
else:
    print("Not answered (or call detection needs tuning)")

print("\nADB controller test complete!")
