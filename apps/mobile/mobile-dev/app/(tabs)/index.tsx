import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Audio, InterruptionModeAndroid, InterruptionModeIOS } from 'expo-av';
import { Image } from 'expo-image';
import Constants from 'expo-constants';
import * as FileSystem from 'expo-file-system/legacy';
import { fromByteArray, toByteArray } from 'base64-js';
import { ActivityIndicator, Pressable, StyleSheet, TextInput } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';

type ExpoExtra = {
  mockVoiceUrl?: string;
};

const getDefaultServerUrl = (): string => {
  const envUrl = process.env.EXPO_PUBLIC_MOCK_VOICE_URL;
  if (envUrl) {
    return envUrl;
  }

  const extra = (Constants.expoConfig?.extra ?? {}) as ExpoExtra;
  if (extra.mockVoiceUrl) {
    return extra.mockVoiceUrl;
  }

  const manifestExtra = (Constants as unknown as { manifest2?: { extra?: ExpoExtra } }).manifest2?.extra;
  if (manifestExtra?.mockVoiceUrl) {
    return manifestExtra.mockVoiceUrl;
  }

  return '';
};

const arrayBufferToBase64 = (buffer: ArrayBuffer): string => {
  const bytes = new Uint8Array(buffer);
  return fromByteArray(bytes);
};

const getBase64Encoding = (): FileSystem.EncodingType => {
  const encodingType = (FileSystem as unknown as {
    EncodingType?: { Base64?: FileSystem.EncodingType };
  }).EncodingType;
  if (encodingType?.Base64) {
    return encodingType.Base64;
  }
  return 'base64' as FileSystem.EncodingType;
};

const BASE64_ENCODING = getBase64Encoding();

const decodeBase64ToUtf8 = (value: string): string => {
  try {
    const bytes = toByteArray(value);
    return new TextDecoder('utf-8').decode(bytes);
  } catch {
    return value;
  }
};

const RECORDING_OPTIONS = Audio.RecordingOptionsPresets.HIGH_QUALITY;

const renderModeName = (mode: string | null | undefined): string => {
  switch (mode) {
    case 'morning':
      return 'モーニング（朝のタスク整理）';
    case 'random':
      return 'おかんチェック';
    default:
      return '未設定';
  }
};

const normalizeBaseUrl = (input: string): string => {
  const trimmed = input.trim();
  if (!trimmed) {
    return '';
  }
  return trimmed
    .replace(/\/session\/start\/?$/i, '')
    .replace(/\/session\/[^/]+\/continue\/?$/i, '')
    .replace(/\/static\/?$/i, '')
    .replace(/\/+$/, '');
};

const buildEndpoint = (
  baseInput: string,
  target: 'start' | 'continue',
  sessionId?: string | null,
): string | null => {
  const base = normalizeBaseUrl(baseInput);
  if (!base) {
    return null;
  }
  if (target === 'start') {
    return `${base}/session/start`;
  }
  if (!sessionId) {
    return null;
  }
  return `${base}/session/${sessionId}/continue`;
};

export default function HomeScreen() {
  const [sound, setSound] = useState<Audio.Sound | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [serverUrl, setServerUrl] = useState(getDefaultServerUrl());
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [responseText, setResponseText] = useState<string | null>(null);
  const [recording, setRecording] = useState<Audio.Recording | null>(null);
  const recordingRef = useRef<Audio.Recording | null>(null);
  const [recordPermissionGranted, setRecordPermissionGranted] = useState<boolean | null>(null);
  const cacheFileUriRef = useRef<string | null>(null);
  const [conversationMode, setConversationMode] = useState<string | null>(null);
  const [nextConversationMode, setNextConversationMode] = useState<string | null>(null);

  useEffect(() => {
    Audio.setAudioModeAsync({
      allowsRecordingIOS: false,
      staysActiveInBackground: false,
      interruptionModeAndroid: InterruptionModeAndroid.DoNotMix,
      interruptionModeIOS: InterruptionModeIOS.DoNotMix,
      playsInSilentModeIOS: true,
      shouldDuckAndroid: true,
    }).catch((err) => {
      setErrorMessage(err.message ?? String(err));
    });
  }, []);

  useEffect(() => {
    Audio.requestPermissionsAsync()
      .then((permissions) => {
        setRecordPermissionGranted(permissions.status === 'granted');
      })
      .catch((err) => {
        setErrorMessage(err.message ?? String(err));
        setRecordPermissionGranted(false);
      });
  }, []);

  useEffect(() => {
    return () => {
      if (sound) {
        sound.unloadAsync().catch(() => undefined);
      }
      const cached = cacheFileUriRef.current;
      if (cached) {
        FileSystem.deleteAsync(cached, { idempotent: true }).catch(() => undefined);
      }
    };
  }, [sound]);

  const recordButtonLabel = useMemo(() => {
    if (isUploading) {
      return '送信中…';
    }
    if (isRecording) {
      return '録音停止';
    }
    if (conversationMode === 'random') {
      return '録音開始（おかんチェック）';
    }
    if (conversationMode === 'morning') {
      return '録音開始（モーニング）';
    }
    return '録音開始';
  }, [conversationMode, isRecording, isUploading]);

  const stopPlayback = useCallback(async () => {
    if (sound) {
      try {
        await sound.stopAsync();
        await sound.unloadAsync();
      } catch {
        // noop
      }
      setSound(null);
    }
    setIsPlaying(false);
    if (cacheFileUriRef.current) {
      await FileSystem.deleteAsync(cacheFileUriRef.current, { idempotent: true }).catch(
        () => undefined,
      );
      cacheFileUriRef.current = null;
    }
  }, [sound]);

  const playResponseAudio = useCallback(
    async (audioBuffer: ArrayBuffer) => {
      await stopPlayback();
      const base64 = arrayBufferToBase64(audioBuffer);
      const fileUri = `${FileSystem.cacheDirectory}voice-response-${Date.now()}.mp3`;
      await FileSystem.writeAsStringAsync(fileUri, base64, { encoding: BASE64_ENCODING });
      cacheFileUriRef.current = fileUri;

      const { sound: newSound } = await Audio.Sound.createAsync({ uri: fileUri });
      newSound.setOnPlaybackStatusUpdate((status) => {
        if (!status.isLoaded) {
          if ('error' in status && status.error) {
            setErrorMessage(status.error);
          }
          return;
        }
        if (status.didJustFinish) {
          setIsPlaying(false);
          newSound.unloadAsync().catch(() => undefined);
          setSound(null);
          if (cacheFileUriRef.current) {
            FileSystem.deleteAsync(cacheFileUriRef.current, { idempotent: true }).catch(
              () => undefined,
            );
            cacheFileUriRef.current = null;
          }
        }
      });

      setSound(newSound);
      setIsPlaying(true);
      await newSound.playAsync();
    },
    [stopPlayback],
  );

  const uploadRecording = useCallback(
    async (uri: string) => {
      setIsUploading(true);
      setErrorMessage(null);
      try {
        const endpoint =
          sessionId === null
            ? buildEndpoint(serverUrl, 'start')
            : buildEndpoint(serverUrl, 'continue', sessionId);

        if (!endpoint) {
          throw new Error('サーバーURLの形式を確認してください。');
        }

        const formData = new FormData();
        formData.append('language_code', 'ja-JP');
        if (sessionId) {
          formData.append('session_id', sessionId);
        }
        formData.append('audio', {
          uri,
          name: `recording-${Date.now()}.m4a`,
          type: 'audio/mp4',
        } as unknown as Blob);

        const response = await fetch(endpoint, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          const text = await response.text().catch(() => '');
          throw new Error(`サーバーエラー: HTTP ${response.status} ${text}`);
        }

        const responseMode = response.headers.get('x-conversation-mode');
        const responseNextMode = response.headers.get('x-conversation-next-mode');
        setConversationMode(responseMode);
        setNextConversationMode(
          responseNextMode && responseNextMode !== responseMode ? responseNextMode : null,
        );

        const sessionHeader = response.headers.get('x-session-id');
        if (sessionHeader) {
          setSessionId(sessionHeader);
        }

        const encodedText = response.headers.get('x-response-text-base64');
        if (encodedText) {
          setResponseText(decodeBase64ToUtf8(encodedText));
        } else {
          setResponseText(null);
        }

        const responseAudio = await response.arrayBuffer();
        await playResponseAudio(responseAudio);
      } finally {
        setIsUploading(false);
      }
    },
    [playResponseAudio, serverUrl, sessionId],
  );

  const resetServerSession = useCallback(async () => {
    if (!sessionId) {
      return;
    }
    const base = normalizeBaseUrl(serverUrl);
    if (!base) {
      return;
    }
    try {
      await fetch(`${base}/session/${sessionId}`, { method: 'DELETE' });
    } catch (error) {
      console.warn('Failed to reset session on server', error);
    }
  }, [serverUrl, sessionId]);

  const startRecording = useCallback(async () => {
    setErrorMessage(null);
    if (!serverUrl.trim()) {
      setErrorMessage('サーバーURLを入力してください。');
      return;
    }

    try {
      const permission = await Audio.requestPermissionsAsync();
      if (!permission.granted) {
        setRecordPermissionGranted(false);
        setErrorMessage('マイクの権限が許可されていません。設定で許可してください。');
        return;
      }
      setRecordPermissionGranted(true);

      await stopPlayback();

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        staysActiveInBackground: false,
        interruptionModeAndroid: InterruptionModeAndroid.DoNotMix,
        interruptionModeIOS: InterruptionModeIOS.DoNotMix,
        playsInSilentModeIOS: true,
        shouldDuckAndroid: true,
      });

      const newRecording = new Audio.Recording();
      recordingRef.current = newRecording;
      await newRecording.prepareToRecordAsync(RECORDING_OPTIONS);
      await newRecording.startAsync();

      setRecording(newRecording);
      setIsRecording(true);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setErrorMessage(message);
      try {
        await Audio.setAudioModeAsync({
          allowsRecordingIOS: false,
          staysActiveInBackground: false,
          interruptionModeAndroid: InterruptionModeAndroid.DoNotMix,
          interruptionModeIOS: InterruptionModeIOS.DoNotMix,
          playsInSilentModeIOS: true,
          shouldDuckAndroid: true,
        });
      } catch {
        // noop
      }
    }
  }, [serverUrl, stopPlayback]);

  const stopRecordingAndUpload = useCallback(async () => {
    if (!recordingRef.current) {
      return;
    }
    setIsRecording(false);
    let uri: string | null = null;
    try {
      await recordingRef.current.stopAndUnloadAsync();
      uri = recordingRef.current.getURI();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setErrorMessage(message);
    } finally {
      recordingRef.current = null;
      setRecording(null);
      try {
        await Audio.setAudioModeAsync({
          allowsRecordingIOS: false,
          staysActiveInBackground: false,
          interruptionModeAndroid: InterruptionModeAndroid.DoNotMix,
          interruptionModeIOS: InterruptionModeIOS.DoNotMix,
          playsInSilentModeIOS: true,
          shouldDuckAndroid: true,
        });
      } catch {
        // noop
      }
    }

    if (!uri) {
      setErrorMessage('録音ファイルを取得できませんでした。');
      return;
    }

    try {
      await uploadRecording(uri);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setErrorMessage(message);
    } finally {
      FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => undefined);
    }
  }, [uploadRecording]);

  const handleRecordToggle = useCallback(() => {
    if (isUploading) {
      return;
    }
    if (isRecording) {
      void stopRecordingAndUpload();
    } else {
      void startRecording();
    }
  }, [isRecording, isUploading, startRecording, stopRecordingAndUpload]);

  const handleResetSession = useCallback(() => {
    void resetServerSession();
    setSessionId(null);
    setResponseText(null);
    setConversationMode(null);
    setNextConversationMode(null);
  }, [resetServerSession]);

  return (
    <ThemedView style={styles.container}>
      <ThemedView style={styles.titleRow}>
        <Image
          source={require('@/assets/images/mom_icon.png')}
          style={styles.titleIcon}
          accessibilityLabel="愛母のアイコン"
        />
        <ThemedText type="title" style={styles.title}>
          
        </ThemedText>
      </ThemedView>
      <ThemedText style={styles.description}>
        URL を指定して録音ボタンを押すと、サーバーへ音声を送信して応答を再生します。初回はセッションを開始し、2 回目以降は継続エンドポイントを呼びます。
      </ThemedText>

      <TextInput
        style={styles.serverInput}
        placeholder="http://192.168.x.x:8000/mock-voice"
        value={serverUrl}
        onChangeText={setServerUrl}
        autoCapitalize="none"
        autoCorrect={false}
        textContentType="URL"
      />

      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: isUploading }}
        style={({ pressed }) => [
          styles.button,
          (isRecording || pressed) && styles.buttonActive,
          isUploading && styles.buttonDisabled,
        ]}
        onPress={handleRecordToggle}
        disabled={isUploading || recordPermissionGranted === false}
      >
        {isUploading ? (
          <ActivityIndicator color="#ffffff" />
        ) : (
          <ThemedText type="defaultSemiBold" style={styles.buttonLabel}>
            {recordButtonLabel}
          </ThemedText>
        )}
      </Pressable>

      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: !sessionId }}
        style={[styles.secondaryButton, !sessionId && styles.buttonDisabled]}
        onPress={handleResetSession}
        disabled={!sessionId}
      >
        <ThemedText style={styles.secondaryButtonLabel}>セッションをリセット</ThemedText>
      </Pressable>

      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: !isPlaying }}
        style={[styles.secondaryButton, !isPlaying && styles.buttonDisabled]}
        onPress={() => stopPlayback()}
        disabled={!isPlaying}
      >
        <ThemedText style={styles.secondaryButtonLabel}>再生を停止</ThemedText>
      </Pressable>

      {conversationMode ? (
        <ThemedView style={styles.modeInfoBox}>
          <ThemedText style={styles.modeInfoLabel}>
            現在のモード: {renderModeName(conversationMode)}
          </ThemedText>
          {nextConversationMode ? (
            <ThemedText style={styles.modeInfoSub}>
              次回は {renderModeName(nextConversationMode)} モードに切り替わります
            </ThemedText>
          ) : null}
          {sessionId ? (
            <ThemedText style={styles.modeInfoMeta}>セッションID: {sessionId}</ThemedText>
          ) : null}
        </ThemedView>
      ) : null}

      {errorMessage ? (
        <ThemedView style={styles.errorBox}>
          <ThemedText type="subtitle" style={styles.errorTitle}>
            エラー
          </ThemedText>
          <ThemedText style={styles.errorMessage}>{errorMessage}</ThemedText>
        </ThemedView>
      ) : null}

      {responseText ? (
        <ThemedView style={styles.infoBox}>
          <ThemedText>
            応答テキスト: <ThemedText type="defaultSemiBold">{responseText}</ThemedText>
          </ThemedText>
        </ThemedView>
      ) : null}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingHorizontal: 24,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 24,
  },
  title: {
    textAlign: 'center',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  titleIcon: {
    width: 48,
    height: 48,
    borderRadius: 12,
  },
  description: {
    textAlign: 'center',
    lineHeight: 22,
  },
  serverInput: {
    width: '100%',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#cbd5f5',
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 16,
    backgroundColor: '#ffffff',
  },
  secondaryButton: {
    width: '100%',
    borderRadius: 999,
    paddingVertical: 12,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#2563eb',
    marginTop: 8,
  },
  secondaryButtonLabel: {
    color: '#2563eb',
    fontSize: 15,
    fontWeight: '600',
  },
  modeInfoBox: {
    width: '100%',
    padding: 16,
    borderRadius: 12,
    backgroundColor: '#e0f2fe',
    borderWidth: 1,
    borderColor: '#38bdf8',
    gap: 4,
  },
  modeInfoLabel: {
    color: '#0f172a',
    fontWeight: '600',
    fontSize: 16,
  },
  modeInfoSub: {
    color: '#1e3a8a',
    fontSize: 14,
  },
  modeInfoMeta: {
    color: '#475569',
    fontSize: 12,
  },
  button: {
    minWidth: 200,
    borderRadius: 999,
    paddingHorizontal: 32,
    paddingVertical: 18,
    backgroundColor: '#2563eb',
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonActive: {
    backgroundColor: '#1d4ed8',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonLabel: {
    color: '#ffffff',
    fontSize: 18,
  },
  errorBox: {
    padding: 16,
    borderRadius: 12,
    backgroundColor: '#fee2e2',
    width: '100%',
  },
  errorTitle: {
    color: '#b91c1c',
    marginBottom: 4,
  },
  errorMessage: {
    color: '#7f1d1d',
  },
  infoBox: {
    width: '100%',
    padding: 16,
    borderRadius: 12,
    backgroundColor: '#eef2ff',
    gap: 8,
  },
});
