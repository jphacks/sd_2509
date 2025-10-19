// App.tsx
import { useEffect } from 'react';
import { View, Button, Platform } from 'react-native';
import * as Notifications from 'expo-notifications';

// 🔸 前面でも通知を表示できるように設定
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,   // アラート表示
    shouldPlaySound: true,   // サウンド鳴動
    shouldSetBadge: false,   // バッジ不要
  }),
});

export default function App() {
  useEffect(() => {
    // 権限リクエスト
    (async () => {
      const { status } = await Notifications.requestPermissionsAsync();
      if (status !== 'granted') {
        alert('通知の許可が必要です');
      }
    })();

    // Android: 通知チャンネル設定（サウンド＆バナー）
    if (Platform.OS === 'android') {
      Notifications.setNotificationChannelAsync('default', {
        name: 'default',
        importance: Notifications.AndroidImportance.MAX,
        vibrationPattern: [0, 250, 250, 250],
        lightColor: '#FF231F7C',
      });
    }
  }, []);

  const sendNotification = async () => {
    await Notifications.scheduleNotificationAsync({
      content: {
        title: '📞 AIからの着信',
        body: '応答しますか？',
        sound: 'default',
      },
      trigger: null, // ← 即時
    });
  };

  return (
    <View style={{ flex:1, justifyContent:'center', alignItems:'center' }}>
      <Button title="通知を送る" onPress={sendNotification} />
    </View>
  );
}

