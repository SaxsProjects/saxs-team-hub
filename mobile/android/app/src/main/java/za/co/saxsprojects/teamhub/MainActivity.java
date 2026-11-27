package za.co.saxsprojects.teamhub;

import android.os.Bundle;
import android.webkit.WebView;

import androidx.webkit.WebSettingsCompat;
import androidx.webkit.WebViewFeature;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Saves previewed documents to Downloads (web pages in the app can't download on their own).
        registerPlugin(TeamHubFilesPlugin.class);
        super.onCreate(savedInstanceState);
        enablePasskeys();
    }

    /**
     * Lets the Team Hub unlock with the phone's fingerprint or face (passkeys). The phone checks the
     * finger or face itself; the app only passes on the signed answer. The website names this app as
     * trusted in /.well-known/assetlinks.json, so only this app (signed with our key) can do it.
     * On phones whose WebView is too old for this, the app simply offers the password.
     */
    private void enablePasskeys() {
        if (getBridge() == null) return;
        WebView webView = getBridge().getWebView();
        if (webView != null && WebViewFeature.isFeatureSupported(WebViewFeature.WEB_AUTHENTICATION)) {
            WebSettingsCompat.setWebAuthenticationSupport(webView.getSettings(), WebSettingsCompat.WEB_AUTHENTICATION_SUPPORT_FOR_APP);
        }
    }
}
