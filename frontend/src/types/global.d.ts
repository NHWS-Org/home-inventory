interface AppConfig {
    VITE_BACKEND_BASE_URL: string;
  }
  interface Window {
    APP_CONFIG: AppConfig;
  }

declare module 'qrcode' {
  const QRCode: {
    toDataURL(
      text: string,
      options?: { errorCorrectionLevel?: 'L' | 'M' | 'Q' | 'H'; margin?: number; width?: number },
    ): Promise<string>;
  };
  export default QRCode;
}
