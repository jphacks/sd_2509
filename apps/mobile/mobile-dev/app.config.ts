import type { ConfigContext, ExpoConfig } from 'expo/config';
import { config as loadEnv } from 'dotenv';
import path from 'path';

const envPath = path.resolve(__dirname, '.env');
loadEnv({ path: envPath });

const appJson = require('./app.json');

export default ({ config }: ConfigContext): ExpoConfig => {
  const base = appJson.expo ?? {};
  const mockVoiceUrl =
    process.env.EXPO_PUBLIC_MOCK_VOICE_URL ?? base.extra?.mockVoiceUrl ?? config.extra?.mockVoiceUrl;

  return {
    ...base,
    ...config,
    extra: {
      ...(base.extra ?? {}),
      ...(config.extra ?? {}),
      mockVoiceUrl,
    },
  };
};
