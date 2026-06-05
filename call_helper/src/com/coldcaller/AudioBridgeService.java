package com.coldcaller;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;

public class AudioBridgeService extends Service {
    private static final String TAG = "ColdCaller";
    private static final int CAPTURE_PORT = 4567;
    private static final int PLAYBACK_PORT = 4568;
    private static final int SAMPLE_RATE = 16000;
    private static final String CHANNEL_ID = "coldcaller_audio";
    private static final int NOTIF_ID = 1001;

    private boolean running;
    private ServerSocket captureServer;
    private ServerSocket playbackServer;
    private Thread captureThread;
    private Thread playbackThread;
    private AudioRecord recorder;
    private AudioTrack player;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
        if (am != null) am.setMode(AudioManager.MODE_IN_COMMUNICATION);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(NOTIF_ID, buildNotification());
        running = true;

        captureThread = new Thread(this::runCaptureServer, "capture-server");
        playbackThread = new Thread(this::runPlaybackServer, "playback-server");
        captureThread.start();
        playbackThread.start();

        Log.i(TAG, "AudioBridgeService started");
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        running = false;
        stopCapture();
        stopPlayback();
        closeQuietly(captureServer);
        closeQuietly(playbackServer);
        AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
        if (am != null) am.setMode(AudioManager.MODE_NORMAL);
        Log.i(TAG, "AudioBridgeService stopped");
        super.onDestroy();
    }

    private void runCaptureServer() {
        try {
            captureServer = new ServerSocket(CAPTURE_PORT);
            Log.i(TAG, "Capture server on port " + CAPTURE_PORT);
            while (running && !captureServer.isClosed()) {
                Socket client = captureServer.accept();
                Log.i(TAG, "Capture client connected");
                runCapture(client);
            }
        } catch (IOException e) {
            if (running) Log.e(TAG, "Capture server: " + e.getMessage());
        }
    }

    private void runCapture(Socket client) {
        int bufferSize = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        Log.i(TAG, "AudioRecord minBufferSize=" + bufferSize
                + " state=" + (recorder != null ? recorder.getState() : "null"));
        if (bufferSize <= 0) bufferSize = SAMPLE_RATE * 2;

        try {
            recorder = new AudioRecord(MediaRecorder.AudioSource.MIC,
                    SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, bufferSize * 2);
            Log.i(TAG, "AudioRecord created, state=" + recorder.getState());
        } catch (Exception e) {
            Log.e(TAG, "AudioRecord(MIC) failed: " + e.getClass().getSimpleName()
                    + ": " + e.getMessage());
            closeQuietly(client);
            return;
        }

        if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
            Log.e(TAG, "AudioRecord init failed");
            closeQuietly(client);
            return;
        }

        try {
            OutputStream out = client.getOutputStream();
            recorder.startRecording();
            Log.i(TAG, "Capture started");
            byte[] buffer = new byte[bufferSize];

            while (running && !client.isClosed()
                    && recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) {
                int read = recorder.read(buffer, 0, buffer.length);
                if (read > 0) {
                    out.write(buffer, 0, read);
                    out.flush();
                }
            }
        } catch (IOException e) {
            Log.w(TAG, "Capture stream: " + e.getMessage());
        } finally {
            stopCapture();
            closeQuietly(client);
            Log.i(TAG, "Capture ended");
        }
    }

    private void runPlaybackServer() {
        try {
            playbackServer = new ServerSocket(PLAYBACK_PORT);
            Log.i(TAG, "Playback server on port " + PLAYBACK_PORT);
            while (running && !playbackServer.isClosed()) {
                Socket client = playbackServer.accept();
                Log.i(TAG, "Playback client connected");
                runPlayback(client);
            }
        } catch (IOException e) {
            if (running) Log.e(TAG, "Playback server: " + e.getMessage());
        }
    }

    private void runPlayback(Socket client) {
        int bufferSize = AudioTrack.getMinBufferSize(SAMPLE_RATE,
                AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (bufferSize <= 0) bufferSize = SAMPLE_RATE * 2;

        try {
            player = new AudioTrack(AudioManager.STREAM_VOICE_CALL,
                    SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, bufferSize, AudioTrack.MODE_STREAM);
        } catch (Exception e) {
            Log.e(TAG, "AudioTrack failed: " + e.getMessage());
            closeQuietly(client);
            return;
        }

        if (player.getState() != AudioTrack.STATE_INITIALIZED) {
            Log.e(TAG, "AudioTrack init failed");
            closeQuietly(client);
            return;
        }

        try {
            InputStream in = client.getInputStream();
            player.play();
            Log.i(TAG, "Playback started");
            byte[] buffer = new byte[bufferSize];

            while (running && !client.isClosed()
                    && player.getPlayState() == AudioTrack.PLAYSTATE_PLAYING) {
                int read = in.read(buffer, 0, buffer.length);
                if (read <= 0) break;
                player.write(buffer, 0, read);
            }
        } catch (IOException e) {
            Log.w(TAG, "Playback stream: " + e.getMessage());
        } finally {
            stopPlayback();
            closeQuietly(client);
            Log.i(TAG, "Playback ended");
        }
    }

    private void stopCapture() {
        if (recorder != null) {
            try {
                if (recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING)
                    recorder.stop();
                recorder.release();
            } catch (Exception ignored) {}
            recorder = null;
        }
    }

    private void stopPlayback() {
        if (player != null) {
            try {
                if (player.getPlayState() == AudioTrack.PLAYSTATE_PLAYING)
                    player.stop();
                player.release();
            } catch (Exception ignored) {}
            player = null;
        }
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, "Audio Bridge",
                    NotificationManager.IMPORTANCE_LOW);
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification() {
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= 26) {
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }
        return builder
                .setContentTitle("Cold Caller")
                .setContentText("Audio bridge active")
                .setSmallIcon(android.R.drawable.ic_media_play)
                .build();
    }

    private void closeQuietly(AutoCloseable c) {
        if (c != null) {
            try { c.close(); } catch (Exception ignored) {}
        }
    }
}
