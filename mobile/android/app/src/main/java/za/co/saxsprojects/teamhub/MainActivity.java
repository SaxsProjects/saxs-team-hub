package za.co.saxsprojects.teamhub;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Saves previewed documents to Downloads (web pages in the app can't download on their own).
        registerPlugin(TeamHubFilesPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
