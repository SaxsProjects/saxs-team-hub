package za.co.saxsprojects.teamhub;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;

import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.util.Arrays;
import java.util.List;

/**
 * Saves a document the person has previewed in the Team Hub. A web page inside the app can't download
 * files on its own, so the page hands the file here. Only the Team Hub's own pages can call this
 * (Capacitor only accepts calls from the configured server), and only document types are accepted.
 */
@CapacitorPlugin(name = "TeamHubFiles")
public class TeamHubFilesPlugin extends Plugin {

    private static final List<String> TYPES = Arrays.asList("application/pdf", "text/csv", "image/png", "image/jpeg", "image/webp");
    private static final int MAX_BYTES = 20 * 1024 * 1024;
    private static final String FOLDER = "Team Hub";

    @PluginMethod
    public void save(PluginCall call) {
        String data = call.getString("data");
        String mimeType = call.getString("mimeType", "application/pdf");
        String filename = safeName(call.getString("filename", "document"));
        if (data == null || data.isEmpty()) {
            call.reject("There is no file to save.");
            return;
        }
        String type = mimeType.split(";")[0].trim().toLowerCase();
        if (!TYPES.contains(type)) {
            call.reject("This kind of file can't be saved from the app.");
            return;
        }
        if (data.length() > (MAX_BYTES / 3) * 4 + 4) {
            call.reject("The file is too large to save.");
            return;
        }
        byte[] bytes;
        try {
            bytes = Base64.decode(data, Base64.DEFAULT);
        } catch (IllegalArgumentException e) {
            call.reject("The file couldn't be read.");
            return;
        }
        try {
            JSObject result = new JSObject();
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                saveToDownloads(bytes, filename, type);
                result.put("location", "Downloads/" + FOLDER);
            } else {
                openFromAppFolder(bytes, filename, type);
                result.put("location", "the app's Downloads folder");
            }
            call.resolve(result);
        } catch (IOException | RuntimeException e) {
            call.reject("The file couldn't be saved. Check the phone has free space and try again.");
        }
    }

    /** Android 10 and later: the shared Downloads folder, no storage permission needed. */
    private void saveToDownloads(byte[] bytes, String filename, String type) throws IOException {
        ContentResolver resolver = getContext().getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.Downloads.DISPLAY_NAME, filename);
        values.put(MediaStore.Downloads.MIME_TYPE, type);
        values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/" + FOLDER);
        values.put(MediaStore.Downloads.IS_PENDING, 1);
        Uri uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
        if (uri == null) throw new IOException("No Downloads folder");
        try (OutputStream out = resolver.openOutputStream(uri)) {
            if (out == null) throw new IOException("Can't write");
            out.write(bytes);
        } catch (IOException e) {
            resolver.delete(uri, null, null);
            throw e;
        }
        values.clear();
        values.put(MediaStore.Downloads.IS_PENDING, 0);
        resolver.update(uri, values, null, null);
    }

    /** Android 7 to 9: keep it in the app's own folder (no permission needed) and open it, so it can be shared or saved. */
    private void openFromAppFolder(byte[] bytes, String filename, String type) throws IOException {
        Context context = getContext();
        File dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
        if (dir == null || (!dir.exists() && !dir.mkdirs())) throw new IOException("No folder");
        File file = new File(dir, filename);
        try (FileOutputStream out = new FileOutputStream(file)) {
            out.write(bytes);
        }
        Uri uri = FileProvider.getUriForFile(context, context.getPackageName() + ".fileprovider", file);
        Intent view = new Intent(Intent.ACTION_VIEW).setDataAndType(uri, type).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        if (view.resolveActivity(context.getPackageManager()) != null) context.startActivity(view);
    }

    /** Keeps a plain file name: no folders, no odd characters. */
    static String safeName(String name) {
        String base = name.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_").replaceAll("^[.\\s]+", "").trim();
        if (base.isEmpty()) base = "document";
        return base.length() > 120 ? base.substring(base.length() - 120) : base;
    }
}
