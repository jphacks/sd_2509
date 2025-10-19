import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Button,
  Text,
  StyleSheet,
  Platform,
  Alert,
  AppState,
} from "react-native";
import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import * as Device from "expo-device";

type ExpoExtra = {
  apiBaseUrl?: string;
  eas?: {
    projectId?: string;
  };
};

type ServerNotificationEvent = {
  id: number;
  title: string;
  body: string;
  created_at: string;
};

type NotificationPollResponse = {
  events?: ServerNotificationEvent[];
  latest_id?: number | null;
};

const extraConfig = Constants.expoConfig?.extra as ExpoExtra | undefined;
const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_BASE_URL ?? extraConfig?.apiBaseUrl ?? "";
const POLL_INTERVAL_MS = 5000;
const ENABLE_SERVER_POLLING = false;
console.log("[App] 起動時 API_BASE_URL =", API_BASE_URL);

// 📱 通知の表示設定（SDK 54対応）
Notifications.setNotificationHandler({
  handleNotification: async () => {
    if (Platform.OS === "ios") {
      return {
        shouldShowBanner: true, // iOS 17+ 対応
        shouldShowList: true,
        shouldPlaySound: true,
        shouldSetBadge: false,
      };
    } else {
      return {
        shouldShowBanner: true,
        shouldShowList: true,
        shouldPlaySound: true,
        shouldSetBadge: false,
      };
    }
  },
});

export default function App() {
  // 📲 通知の権限リクエスト
  useEffect(() => {
    (async () => {
      const { status: existingStatus } = await Notifications.getPermissionsAsync();
      let finalStatus = existingStatus;
      if (existingStatus !== "granted") {
        const requestResult = await Notifications.requestPermissionsAsync();
        finalStatus = requestResult.status;
      }

      console.log("[permissions] status =", finalStatus);
      if (finalStatus !== "granted") {
        Alert.alert("通知の許可が必要です📲");
      }
    })();
  }, []);

  const lastEventIdRef = useRef(0);
  const appStateRef = useRef(AppState.currentState);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (nextState) => {
      console.log("[AppState] change:", appStateRef.current, "->", nextState);
      appStateRef.current = nextState;
    });

    return () => {
      subscription.remove();
    };
  }, []);

  const [devicePushToken, setDevicePushToken] = useState<string | null>(null);

  useEffect(() => {
    if (!Device.isDevice) {
      console.warn("Push通知は実機でのみサポートされています。");
      return;
    }

    (async () => {
      try {
        if (Platform.OS === "android") {
          await Notifications.setNotificationChannelAsync("default", {
            name: "default",
            importance: Notifications.AndroidImportance.MAX,
            vibrationPattern: [0, 250, 250, 250],
            lightColor: "#FF231F7C",
            sound: "default",
            enableVibrate: true,
          });
        }

        const tokenResult = await Notifications.getDevicePushTokenAsync();
        console.log(
          `[push] Device Push Token (${tokenResult.type}) =`,
          tokenResult.data,
        );
        setDevicePushToken(tokenResult.data ?? null);
      } catch (error) {
        console.warn("デバイストークンの取得に失敗しました:", error);
      }
    })();
  }, []);

  useEffect(() => {
    if (!API_BASE_URL || !devicePushToken) {
      return;
    }

    const registerDevice = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/push/register`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            token: devicePushToken,
            platform: Platform.OS,
            app_version: Constants.expoConfig?.version,
          }),
        });
        console.log("[push register] status =", response.status);
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const payload = await response.json();
        console.log("[push register] response:", payload);
      } catch (error) {
        console.warn("Pushトークンの登録に失敗しました:", error);
      }
    };

    void registerDevice();
  }, [API_BASE_URL, devicePushToken]);

  useEffect(() => {
    if (!ENABLE_SERVER_POLLING) {
      console.log("[poll] サーバーポーリングは無効化されています。");
      return;
    }

    if (!API_BASE_URL) {
      console.warn(
        "EXPO_PUBLIC_API_BASE_URL もしくは app.json の extra.apiBaseUrl が設定されていないため、サーバー通知の監視をスキップします。",
      );
      return;
    }

    let isMounted = true;
    let isPolling = false;

    const pollServer = async () => {
      if (isPolling || !isMounted) {
        return;
      }
      isPolling = true;
      try {
        const url = `${API_BASE_URL}/notifications/poll?after=${lastEventIdRef.current}`;
        console.log("[poll] fetching:", url);
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = (await response.json()) as NotificationPollResponse;
        console.log("[poll] response:", data);
        if (!isMounted) {
          return;
        }

        const events = data.events ?? [];
        for (const event of events) {
          console.log("[poll] event:", event);
          lastEventIdRef.current = Math.max(lastEventIdRef.current, event.id);
          void Notifications.scheduleNotificationAsync({
            content: {
              title: event.title,
              body: event.body,
              sound: true,
            },
            trigger: null,
          });
        }

        if (typeof data.latest_id === "number") {
          lastEventIdRef.current = Math.max(
            lastEventIdRef.current,
            data.latest_id,
          );
        }
      } catch (error) {
        console.warn("通知ポーリングに失敗しました:", error);
      } finally {
        isPolling = false;
      }
    };

    const timerId = setInterval(() => {
      void pollServer();
    }, POLL_INTERVAL_MS);

    void pollServer();

    return () => {
      isMounted = false;
      clearInterval(timerId);
    };
  }, []);

  // ⏰ 擬似的に「AIが電話してくる」関数
  const simulateCall = () => {
    console.log("[simulateCall] local notification");
    void Notifications.scheduleNotificationAsync({
      content: {
        title: "🤖 AIからの着信",
        body: "『もしもし、今日の予定を聞かせてください』",
        sound: true,
      },
      trigger: { seconds: 5 }, // 5秒後に通知
    });
  };

  const triggerServerNotification = () => {
    if (!API_BASE_URL) {
      Alert.alert(
        "サーバーURLが未設定です",
        "EXPO_PUBLIC_API_BASE_URL もしくは app.json の extra.apiBaseUrl を設定してください。",
      );
      return;
    }

    const url = `${API_BASE_URL}/notifications/publish`;
    console.log("[triggerServerNotification] POST", url);
    void fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        title: "📡 サーバーからのお知らせ",
        body: "サーバー側でイベントが発生しました。",
      }),
    })
      .then(async (response) => {
        console.log("[triggerServerNotification] status =", response.status);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const payload = await response.json().catch(() => undefined);
        console.log("[triggerServerNotification] response payload:", payload);
        Alert.alert("サーバーに通知を依頼しました");
      })
      .catch((error) => {
        console.warn("サーバー通知の送信に失敗しました:", error);
        Alert.alert(
          "通知の送信に失敗しました",
          error instanceof Error ? error.message : String(error),
        );
      });
  };

  return (
    <View style={styles.container}>
      <Text style={styles.text}>AI電話デモ📞</Text>
      <Button title="AIから電話を受ける" onPress={simulateCall} />
      <View style={styles.buttonWrapper}>
        <Button
          title="サーバーからの通知をリクエスト"
          onPress={triggerServerNotification}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#fff",
  },
  text: {
    fontSize: 20,
    marginBottom: 20,
  },
  buttonWrapper: {
    marginTop: 12,
  },
});
