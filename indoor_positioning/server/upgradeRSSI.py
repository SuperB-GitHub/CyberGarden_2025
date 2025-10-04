import numpy as np
from scipy.optimize import curve_fit

class RSSIProcessor:
    """
    Лёгкий класс для обработки RSSI в indoor-позиционировании.
    Включает калибровку, минимальную предобработку и адаптивный фильтр Калмана.
    """
    def __init__(self, measured_power=-60, path_loss_exponent=3.0, process_variance=1.0, measurement_variance=4.0):
        """
        Инициализация:
        - measured_power: P0 (сила на 1м, дБм)
        - path_loss_exponent: n (коэффициент затухания)
        - process_variance: Q для Kalman (шум модели, увеличен для адаптивности)
        - measurement_variance: R для Kalman (шум измерений)
        """
        self.measured_power = measured_power
        self.n = path_loss_exponent
        # Kalman state
        self.kf_x = measured_power  # Начальная оценка RSSI
        self.kf_P = 1.0  # Начальная коварианция ошибки
        self.Q = process_variance  # Увеличен для большей чувствительности
        self.R = measurement_variance

    def rssi_to_distance(self, rssi):
        """Преобразование RSSI в расстояние по log-distance модели."""
        if rssi >= self.measured_power:
            return 1.0  # Минимальное расстояние
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
            print(f"Калиброванные параметры: P0={popt[0]:.2f}, n={popt[1]:.2f}")
            return popt
        except Exception as e:
            print(f"Ошибка калибровки: {e}, используются дефолтные P0={self.measured_power}, n={self.n}")
            return None

    def clean_rssi(self, rssi_sequence):
        """
        Минимальная предобработка: проверка входа и замена NaN на медиану.
        rssi_sequence: список/массив RSSI
        Возвращает: очищенный массив RSSI
        """
        if not rssi_sequence:
            print("Предупреждение: пустая входная последовательность")
            return np.array([])

        try:
            rssi_seq = np.array(rssi_sequence, dtype=float)
        except (ValueError, TypeError) as e:
            print(f"Ошибка: некорректные входные данные - {e}")
            return np.array([])

        print("Входной RSSI:", rssi_seq)

        # Замена NaN на медиану
        if np.any(np.isnan(rssi_seq)):
            median_val = np.nanmedian(rssi_seq)
            rssi_seq = np.nan_to_num(rssi_seq, nan=median_val)
            print("RSSI после замены NaN:", rssi_seq)

        return rssi_seq

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
        Полная обработка: минимальная очистка + Kalman.
        rssi_sequence: сырая последовательность RSSI
        Возвращает: сглаженный массив RSSI
        """
        cleaned_rssi = self.clean_rssi(rssi_sequence)
        if len(cleaned_rssi) == 0:
            print("Предупреждение: после очистки получен пустой массив")
            return np.array([])

        # Сброс Kalman state для новой последовательности
        self.kf_x = cleaned_rssi[0] if len(cleaned_rssi) > 0 else self.measured_power
        self.kf_P = 1.0
        # Применение Kalman
        final_rssi = [self.kalman_update(rssi) for rssi in cleaned_rssi]
        print("Финальный RSSI (после Kalman):", final_rssi)
        return np.array(final_rssi)