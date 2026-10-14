// Voice language codes for the news briefing.

export const CA_VOICE_LANGUAGES = [
  { code: "hi", tts: "hi-IN", name: "Hindi", native_name: "हिन्दी" },
  { code: "en", tts: "en-IN", name: "English", native_name: "English" },
  { code: "bn", tts: "bn-IN", name: "Bengali", native_name: "বাংলা" },
  { code: "ta", tts: "ta-IN", name: "Tamil", native_name: "தமிழ்" },
  { code: "te", tts: "te-IN", name: "Telugu", native_name: "తెలుగు" },
  { code: "mr", tts: "mr-IN", name: "Marathi", native_name: "मराठी" },
  { code: "kn", tts: "kn-IN", name: "Kannada", native_name: "ಕನ್ನಡ" },
  { code: "gu", tts: "gu-IN", name: "Gujarati", native_name: "ગુજરાતી" },
  { code: "ml", tts: "ml-IN", name: "Malayalam", native_name: "മലയാളം" },
  { code: "pa", tts: "pa-IN", name: "Punjabi", native_name: "ਪੰਜਾਬੀ" },
  { code: "od", tts: "od-IN", name: "Odia", native_name: "ଓଡ଼ିଆ" },
] as const;

export function ttsCodeForVoice(code: string): string {
  return CA_VOICE_LANGUAGES.find((lang) => lang.code === code)?.tts ?? "hi-IN";
}
