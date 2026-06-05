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
            int subId = -1;
            PhoneAccountHandle targetHandle = null;

            if (simSlot >= 0) {
                SubscriptionManager subManager = (SubscriptionManager) getSystemService(TELEPHONY_SUBSCRIPTION_SERVICE);
                if (subManager != null) {
                    List<SubscriptionInfo> subs = subManager.getActiveSubscriptionInfoList();
                    Log.i(TAG, "Active subscriptions: " + (subs != null ? subs.size() : "null"));
                    if (subs != null) {
                        for (SubscriptionInfo sub : subs) {
                            Log.i(TAG, "  sub: slot=" + sub.getSimSlotIndex()
                                + " subId=" + sub.getSubscriptionId()
                                + " carrier=" + sub.getCarrierName());
                        }
                        for (SubscriptionInfo sub : subs) {
                            if (sub.getSimSlotIndex() == simSlot) {
                                subId = sub.getSubscriptionId();
                                Log.i(TAG, "Target subId=" + subId + " for slot=" + simSlot);
                                break;
                            }
                        }
                    }
                }

                TelecomManager telecom = (TelecomManager) getSystemService(TELECOM_SERVICE);
                if (telecom != null) {
                    List<PhoneAccountHandle> accounts = telecom.getCallCapablePhoneAccounts();
                    Log.i(TAG, "Phone accounts: " + (accounts != null ? accounts.size() : "null"));
                    if (accounts != null) {
                        for (PhoneAccountHandle handle : accounts) {
                            Log.i(TAG, "  account: " + handle.getId() + " (" + handle.getComponentName() + ")");
                        }
                        for (PhoneAccountHandle handle : accounts) {
                            String id = handle.getId();
                            if (id != null && (id.equals(String.valueOf(subId))
                                    || id.endsWith(":" + simSlot)
                                    || id.endsWith("/" + simSlot)
                                    || id.equals("sim" + simSlot)
                                    || id.equals("sub" + simSlot)
                                    || id.equals(String.valueOf(simSlot)))) {
                                targetHandle = handle;
                                Log.i(TAG, "Matched PhoneAccountHandle: " + id);
                                break;
                            }
                        }
                    }
                }
            }

            boolean placed = tryDialerDirect(telUri, simSlot, subId);
            if (!placed) placed = tryPlaceCallViaTelecom(telUri, targetHandle, simSlot, subId);
            if (!placed) placed = tryITelephonyCall(phoneNumber, subId);
            if (!placed) placed = tryPlaceCallViaIntent(telUri, simSlot, subId);

            setResult(placed ? RESULT_OK : RESULT_CANCELED);
        } catch (Exception e) {
            Log.e(TAG, "Exception: " + e.getClass().getName() + ": " + e.getMessage());
            setResult(RESULT_CANCELED);
        }

        finish();
    }

    private boolean tryDialerDirect(Uri telUri, int simSlot, int subId) {
        try {
            TelecomManager telecom = (TelecomManager) getSystemService(TELECOM_SERVICE);
            if (telecom == null) return false;

            String defaultDialer = telecom.getDefaultDialerPackage();
            Log.i(TAG, "Default dialer package: " + defaultDialer);

            Intent intent = new Intent(Intent.ACTION_CALL, telUri);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            if (defaultDialer != null) {
                intent.setPackage(defaultDialer);
            }
            if (simSlot >= 0) {
                intent.putExtra("com.android.phone.extra.slot", simSlot);
                intent.putExtra("slot", simSlot);
                if (subId > 0) {
                    intent.putExtra("subscription", subId);
                    intent.putExtra(SubscriptionManager.EXTRA_SUBSCRIPTION_INDEX, subId);
                }
            }
            startActivity(intent);
            Log.i(TAG, "Dialer direct call succeeded");
            return true;
        } catch (Exception e) {
            Log.w(TAG, "Dialer direct failed: " + e.getMessage());
            return false;
        }
    }

    private boolean tryITelephonyCall(String number, int subId) {
        try {
            TelephonyManager tm = (TelephonyManager) getSystemService(TELEPHONY_SERVICE);
            Method getITelephony = tm.getClass().getDeclaredMethod("getITelephony");
            getITelephony.setAccessible(true);
            Object telephony = getITelephony.invoke(tm);

            Log.i(TAG, "ITelephony methods:");
            for (Method m : telephony.getClass().getMethods()) {
                String name = m.getName();
                if (name.contains("call") || name.contains("dial") || name.contains("place")) {
                    StringBuilder sb = new StringBuilder();
                    sb.append("  ").append(name).append("(");
                    for (Class<?> p : m.getParameterTypes()) {
                        sb.append(p.getSimpleName()).append(",");
                    }
                    sb.append(")");
                    Log.i(TAG, sb.toString());
                }
            }

            String[][] callSignatures = {
                {"call", String.class.getName(), int.class.getName()},
                {"call", String.class.getName(), String.class.getName(), int.class.getName()},
                {"call", String.class.getName(), String.class.getName()},
                {"dial", String.class.getName(), int.class.getName()},
            };

            for (String[] sig : callSignatures) {
                try {
                    Class<?>[] paramTypes = new Class<?>[sig.length - 1];
                    for (int i = 0; i < paramTypes.length; i++) {
                        paramTypes[i] = Class.forName(sig[i + 1]);
                    }
                    Method m = telephony.getClass().getMethod(sig[0], paramTypes);
                    Object[] args = new Object[paramTypes.length];
                    if (paramTypes.length == 2 && paramTypes[1] == int.class) {
                        args[0] = number;
                        args[1] = subId;
                    } else if (paramTypes.length == 3) {
                        args[0] = getPackageName();
                        args[1] = number;
                        args[2] = subId;
                    } else if (paramTypes.length == 2 && paramTypes[1] == String.class) {
                        args[0] = number;
                        args[1] = String.valueOf(subId);
                    }
                    m.invoke(telephony, args);
                    Log.i(TAG, sig[0] + " succeeded");
                    return true;
                } catch (NoSuchMethodException e) {
                    // try next
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "ITelephony call failed: " + e.getMessage());
        }
        return false;
    }

    private boolean tryPlaceCallViaTelecom(Uri telUri, PhoneAccountHandle handle, int simSlot, int subId) {
        try {
            TelecomManager telecom = (TelecomManager) getSystemService(TELECOM_SERVICE);
            if (telecom == null) return false;

            Bundle extras = new Bundle();
            if (handle != null) {
                extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE, handle);
                Log.i(TAG, "TelecomManager.placeCall with handle=" + handle.getId());
            }
            extras.putInt("com.android.phone.extra.slot", simSlot);
            extras.putInt("slot", simSlot);
            if (subId > 0) {
                extras.putInt("subscription", subId);
                extras.putInt(SubscriptionManager.EXTRA_SUBSCRIPTION_INDEX, subId);
            }

            telecom.placeCall(telUri, extras);
            Log.i(TAG, "TelecomManager.placeCall succeeded");
            return true;
        } catch (SecurityException e) {
            Log.w(TAG, "TelecomManager.placeCall SecurityException: " + e.getMessage());
        } catch (Exception e) {
            Log.w(TAG, "TelecomManager.placeCall failed: " + e.getMessage());
        }
        return false;
    }

    private boolean tryPlaceCallViaIntent(Uri telUri, int simSlot, int subId) {
        try {
            Intent callIntent = new Intent(Intent.ACTION_CALL, telUri);
            callIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            if (simSlot >= 0) {
                callIntent.putExtra("com.android.phone.extra.slot", simSlot);
                callIntent.putExtra("slot", simSlot);
                if (subId > 0) {
                    callIntent.putExtra("subscription", subId);
                    callIntent.putExtra("simId", subId);
                    callIntent.putExtra("subscription_id", subId);
                    callIntent.putExtra("sub_id", subId);
                    callIntent.putExtra(SubscriptionManager.EXTRA_SUBSCRIPTION_INDEX, subId);
                }
            }
            startActivity(callIntent);
            Log.i(TAG, "Intent.ACTION_CALL succeeded");
            return true;
        } catch (SecurityException e) {
            Log.w(TAG, "Intent.ACTION_CALL SecurityException: " + e.getMessage());
        } catch (Exception e) {
            Log.w(TAG, "Intent.ACTION_CALL failed: " + e.getMessage());
        }
        return false;
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
                if ((name.contains("end") || name.contains("hangup")) && m.getParameterCount() == 0) {
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
