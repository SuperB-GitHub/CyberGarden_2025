import numpy as np
from scipy.optimize import curve_fit
from scipy import signal

class RSSIProcessor:
    """
    Класс для обработки и улучшения сигнала RSSI в indoor-позиционировании.
    Включает калибровку, предобработку, сглаживание Kalman и расчет расстояния.
    """
    def __init__(self, measured_power=-60, path_loss_exponent=3.0, process_variance=0.1, measurement_variance=4.0):
        """
        Инициализация:
        - measured_power: P0 (сила на 1м, дБм)
        - path_loss_exponent: n (коэффициент затухания)
        - process_variance: Q для Kalman (шум модели)
        - measurement_variance: R для Kalman (шум измерений)
        """
        self.measured_power = measured_power
        self.n = path_loss_exponent
        self.kf_x = measured_power  
        self.kf_P = 1.0 
        self.Q = process_variance
        self.R = measurement_variance

    def rssi_to_distance(self, rssi):
        """Преобразование RSSI в расстояние по log-distance модели."""
        if rssi >= self.measured_power:
            return 1.0 
        return 10 ** ((self.measured_power - rssi) / (10 * self.n))

    def calibrate_parameters(self, distances, rssi_values):
        """
        Калибровка P0 и n на основе данных.
        distances: массив расстояний (м)
        rssi_values: массив измеренных RSSI
        Возвращает: [P0, n] или None при ошибке
        """
        def path_loss_model(d, P0, n):
            return P0 - 10 * n * np.log10(d)
        try:
            popt, _ = curve_fit(path_loss_model, np.array(distances), np.array(rssi_values))
            self.measured_power, self.n = popt
            return popt
        except Exception as e:
            print(f"Calibration error: {e}")
            return None

    def preprocess_rssi(self, rssi_sequence, kernel_size=3, low_threshold=-90, high_threshold=-30):
        """
        Предобработка: отсев outliers, замена NaN, медианный фильтр.
        rssi_sequence: список/массив RSSI
        kernel_size: размер ядра для medfilt
        thresholds: пороги для отсева
        """
        rssi_seq = np.array(rssi_sequence)
        rssi_seq[(rssi_seq < low_threshold) | (rssi_seq > high_threshold)] = np.nan
        if np.all(np.isnan(rssi_seq)):
            return np.array([])
        median_val = np.nanmedian(rssi_seq)
        rssi_seq = np.nan_to_num(rssi_seq, nan=median_val)
        filtered = signal.medfilt(rssi_seq, kernel_size=kernel_size)
        return filtered

    def kalman_update(self, measurement):
        """Обновление Kalman для одного измерения RSSI."""
        x_pred = self.kf_x
        P_pred = self.kf_P + self.Q
        K = P_pred / (P_pred + self.R)
        self.kf_x = x_pred + K * (measurement - x_pred)
        self.kf_P = (1 - K) * P_pred
        return self.kf_x

    def process_rssi(self, rssi_sequence):
        """
        Полная обработка: предобработка + Kalman.
        rssi_sequence: сырая последовательность RSSI
        Возвращает: сглаженный массив RSSI
        """
        preprocessed = self.preprocess_rssi(rssi_sequence)
        if len(preprocessed) == 0:
            return np.array([])
        self.kf_x = preprocessed[0]
        self.kf_P = 1.0
        smoothed = [self.kalman_update(rssi) for rssi in preprocessed]
        return np.array(smoothed)