package com.coldcaller;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.IBinder;
import android.telecom.PhoneAccountHandle;
import android.telecom.TelecomManager;
import android.telephony.SubscriptionInfo;
import android.telephony.SubscriptionManager;
import android.telephony.TelephonyManager;
import android.util.Log;
import java.lang.reflect.Method;
import java.util.List;

public class CallHelper extends Activity {
    private static final String TAG = "ColdCaller";
    private static final String EXTRA_SIM_SLOT = "sim_slot";
    private static final String ACTION_HANGUP = "com.coldcaller.HANGUP";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Intent intent = getIntent();
        String action = intent.getAction();

        if (ACTION_HANGUP.equals(action)) {
            setResult(doHangup() ? RESULT_OK : RESULT_CANCELED);
            finish();
            return;
        }

        doCall(intent);
    }

    private void doCall(Intent intent) {
        String phoneNumber = null;

        if (intent.getData() != null) {
            phoneNumber = intent.getData().getSchemeSpecificPart();
        }
        if (phoneNumber == null && intent.hasExtra(Intent.EXTRA_PHONE_NUMBER)) {
            phoneNumber = intent.getStringExtra(Intent.EXTRA_PHONE_NUMBER);
        }
        if (phoneNumber == null) {
            Log.e(TAG, "No phone number provided");
            setResult(RESULT_CANCELED);
            finish();
            return;
        }

        int simSlot = intent.getIntExtra(EXTRA_SIM_SLOT, -1);
        Log.i(TAG, "Calling " + phoneNumber + " slot=" + simSlot);

        try {
            Uri telUri = Uri.parse("tel:" + phoneNumber);
            Intent callIntent = new Intent(Intent.ACTION_CALL, telUri);
            callIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);

            if (simSlot >= 0) {
                SubscriptionManager subManager = (SubscriptionManager) getSystemService(TELEPHONY_SUBSCRIPTION_SERVICE);
                if (subManager != null) {
                    List<SubscriptionInfo> subs = subManager.getActiveSubscriptionInfoList();
                    if (subs != null) {
                        for (SubscriptionInfo sub : subs) {
                            Log.i(TAG, "  sub: slot=" + sub.getSimSlotIndex()
                                + " subId=" + sub.getSubscriptionId()
                                + " carrier=" + sub.getCarrierName());
                        }
                        for (SubscriptionInfo sub : subs) {
                            if (sub.getSimSlotIndex() == simSlot) {
                                callIntent.putExtra("com.android.phone.extra.slot", simSlot);
                                callIntent.putExtra("slot", simSlot);
                                Log.i(TAG, "Set MTK extras for slot=" + simSlot
                                    + " (subId=" + sub.getSubscriptionId() + ")");
                                break;
                            }
                        }
                    }
                }

                TelecomManager telecom = (TelecomManager) getSystemService(TELECOM_SERVICE);
                if (telecom != null) {
                    List<PhoneAccountHandle> accounts = telecom.getCallCapablePhoneAccounts();
                    if (accounts != null) {
                        for (PhoneAccountHandle handle : accounts) {
                            String id = handle.getId();
                            Log.i(TAG, "  account: " + id + " (" + handle.getComponentName() + ")");
                            if (id != null && id.contains(String.valueOf(simSlot))) {
                                callIntent.putExtra(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE, handle);
                                Log.i(TAG, "Set PhoneAccountHandle: " + id);
                                break;
                            }
                        }
                    }
                }
            }

            startActivity(callIntent);
            Log.i(TAG, "Call initiated");
            setResult(RESULT_OK);
        } catch (SecurityException e) {
            Log.e(TAG, "SecurityException: " + e.getMessage());
            setResult(RESULT_CANCELED);
        } catch (Exception e) {
            Log.e(TAG, "Exception: " + e.getClass().getName() + ": " + e.getMessage());
            setResult(RESULT_CANCELED);
        }

        finish();
    }

    private boolean doHangup() {
        Log.i(TAG, "Hanging up");

        if (tryTelephonyEndCall()) return true;
        if (tryTelecomEndCall()) return true;
        if (tryServiceManagerPhone()) return true;

        Log.w(TAG, "All hangup methods failed");
        return false;
    }

    private boolean tryTelephonyEndCall() {
        try {
            TelephonyManager tm = (TelephonyManager) getSystemService(TELEPHONY_SERVICE);
            Method getITelephony = tm.getClass().getDeclaredMethod("getITelephony");
            getITelephony.setAccessible(true);
            Object telephony = getITelephony.invoke(tm);

            Method endCall = telephony.getClass().getDeclaredMethod("endCall");
            endCall.invoke(telephony);
            Log.i(TAG, "Hangup via ITelephony.endCall() succeeded");
            return true;
        } catch (Exception e) {
            Log.w(TAG, "ITelephony.endCall() failed: " + e.getMessage());
            return false;
        }
    }

    private boolean tryTelecomEndCall() {
        try {
            TelecomManager telecom = (TelecomManager) getSystemService(TELECOM_SERVICE);
            Method getTelecomService = telecom.getClass().getDeclaredMethod("getTelecomService");
            getTelecomService.setAccessible(true);
            Object iTelecom = getTelecomService.invoke(telecom);

            Method endCall = iTelecom.getClass().getMethod("endCall");
            endCall.invoke(iTelecom);
            Log.i(TAG, "Hangup via ITelecomService.endCall() succeeded");
            return true;
        } catch (Exception e) {
            Log.w(TAG, "ITelecomService.endCall() failed: " + e.getMessage());
            return false;
        }
    }

    private boolean tryServiceManagerPhone() {
        try {
            Class<?> smClass = Class.forName("android.os.ServiceManager");
            Method getService = smClass.getMethod("getService", String.class);
            IBinder binder = (IBinder) getService.invoke(null, "phone");
            if (binder == null) {
                Log.w(TAG, "phone service (binder) not found");
                return false;
            }

            Class<?> iTelephony = Class.forName("com.android.internal.telephony.ITelephony");
            Method asInterface = iTelephony.getMethod("asInterface", IBinder.class);
            Object telephony = asInterface.invoke(null, binder);

            for (Method m : telephony.getClass().getMethods()) {
                String name = m.getName().toLowerCase();
                if ((name.contains("end") || name.contains("hangup"))
                        && m.getParameterCount() == 0) {
                    Log.i(TAG, "Trying method: " + m.getName());
                    m.invoke(telephony);
                    Log.i(TAG, m.getName() + " succeeded");
                    return true;
                }
            }
            Log.w(TAG, "No end/hangup method found on ITelephony");
        } catch (Exception e) {
            Log.w(TAG, "ServiceManager phone approach failed: " + e.getMessage());
        }
        return false;
    }
}
