"""
Indoor Positioning System - Positioning Evaluations Module

Этот модуль реализует вычисления для позиционирования в помещении.
Обрабатывает данные от ESP32 якорей и вычисляет позиции устройств
"""
"""
Indoor Positioning System - Enhanced Positioning Evaluations Module
"""

import numpy as np
import logging
from typing import Dict, List, Tuple, Optional, Any
from scipy.optimize import minimize
import numpy.linalg as la

logger = logging.getLogger(__name__)


class EnhancedTrilaterationEngine:
    """Улучшенный движок для расчета позиции с использованием расширенных данных."""

    def __init__(self, room_config: Dict[str, Any]) -> None:
        self.room_config = room_config

    def calculate_position(self, anchor_measurements: Dict[str, Any]) -> Optional[Dict[str, float]]:
        """Основная функция расчета позиции с использованием расширенных данных."""
        try:
            # Проверяем что anchor_measurements - это словарь с данными
            if not anchor_measurements or len(anchor_measurements) < 2:
                print(f"⚠️  Not enough anchor measurements: {len(anchor_measurements)}")
                return None

            print(f"🎯 Начало расчета позиции для {len(anchor_measurements)} якорей")

            # Детальная проверка структуры данных
            for anchor_id, measurements in anchor_measurements.items():
                print(f"   🔍 Anchor {anchor_id}: {len(measurements)} measurements")
                if not isinstance(measurements, list) or not measurements:
                    print(f"   ⚠️  Invalid measurements for anchor {anchor_id}: {type(measurements)}")
                    return None

                # Проверяем первое измерение
                first_measurement = measurements[0]
                if not isinstance(first_measurement, dict):
                    print(f"   ⚠️  Invalid measurement type for anchor {anchor_id}: {type(first_measurement)}")
                    return None

                print(f"   📏 Measurement keys: {list(first_measurement.keys())}")

            # Взвешиваем измерения по уверенности
            weighted_measurements = self._apply_measurement_weights(anchor_measurements)

            if not weighted_measurements:
                print("⚠️  No valid weighted measurements")
                return None

            print(f"   ✅ Weighted measurements: {len(weighted_measurements)} anchors")

            # Пробуем последовательно разные методы с улучшенными данными
            position = self.enhanced_trilateration_3d(weighted_measurements)
            if not position or not self.is_valid_position(position):
                print("   🔄 Trying confidence weighted centroid")
                position = self.confidence_weighted_centroid(weighted_measurements)
            if not position or not self.is_valid_position(position):
                print("   🔄 Trying adaptive geometric method")
                position = self.adaptive_geometric_method(weighted_measurements)
            if position and not self.is_valid_position(position):
                print("   🔄 Correcting position")
                position = self.correct_position(position)

            return position

        except Exception as e:
            print(f"❌ Ошибка расчета позиции: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _apply_measurement_weights(self, anchor_measurements: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Применяет веса к измерениям на основе уверенности и других факторов."""
        weighted_data = {}

        for anchor_id, measurements in anchor_measurements.items():
            if not measurements or not isinstance(measurements, list):
                continue

            # Берем последнее измерение
            latest_measurement = measurements[-1]

            # Проверяем структуру измерения
            if not isinstance(latest_measurement, dict):
                continue

            # Базовый вес на основе уверенности в расстоянии
            confidence_weight = latest_measurement.get('distance_confidence', 0.5)

            # Дополнительный вес на основе количества пакетов
            packet_weight = min(1.0, latest_measurement.get('packet_count', 1) / 10.0)

            # Вес на основе согласованности канала
            channel_weight = latest_measurement.get('channel_consistency', 0.5)

            # Общий вес измерения
            total_weight = (confidence_weight * 0.6 +
                            packet_weight * 0.25 +
                            channel_weight * 0.15)

            weighted_data[anchor_id] = {
                'distance': latest_measurement.get('distance', 0),
                'weight': total_weight,
                'confidence': confidence_weight,
                'rssi_filtered': latest_measurement.get('rssi_filtered', -70),
                'channel': latest_measurement.get('channel', 1),
                'original_data': latest_measurement
            }

            print(f"   📊 {anchor_id}: distance={latest_measurement.get('distance', 0):.2f}m, "
                  f"weight={total_weight:.2f}, conf={confidence_weight:.2f}")

        return weighted_data

    def enhanced_trilateration_3d(self, weighted_measurements: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, float]]:
        """Улучшенная 3D трилатерация с весами измерений."""
        try:
            if len(weighted_measurements) < 3:
                return None

            print("📍 Используем улучшенную 3D трилатерацию")

            # Подготавливаем данные с весами
            anchors_list = []
            distances_list = []
            weights_list = []

            for anchor_id, data in weighted_measurements.items():
                if anchor_id in self.room_config['anchors']:
                    anchor = self.room_config['anchors'][anchor_id]
                    anchors_list.append([anchor['x'], anchor['y'], anchor['z']])
                    distances_list.append(data['distance'])
                    weights_list.append(data['weight'])

            # Метод наименьших квадратов с весами
            def error_function(pos):
                x, y, z = pos
                total_error = 0.0
                for i, (anchor, dist, weight) in enumerate(zip(anchors_list, distances_list, weights_list)):
                    calculated_dist = np.sqrt((x - anchor[0]) ** 2 + (y - anchor[1]) ** 2 + (z - anchor[2]) ** 2)
                    error = (calculated_dist - dist) ** 2
                    total_error += error * weight
                return total_error

            # Начальное приближение - центр комнаты
            initial_guess = [self.room_config['width'] / 2,
                             self.room_config['height'] / 2,
                             self.room_config.get('depth', 5) / 2]

            # Границы комнаты
            bounds = [(0, self.room_config['width']),
                      (0, self.room_config['height']),
                      (0, self.room_config.get('depth', 5))]

            result = minimize(error_function, initial_guess, bounds=bounds, method='L-BFGS-B')

            if result.success:
                position = {
                    'x': float(result.x[0]),
                    'y': float(result.x[1]),
                    'z': float(result.x[2])
                }

                print(f"✅ Успешная улучшенная 3D трилатерация: {position}")
                return position

            return None

        except Exception as e:
            print(f"Улучшенная 3D трилатерация не удалась: {e}")
            return None

    def confidence_weighted_centroid(self, weighted_measurements: Dict[str, Dict[str, Any]]) -> Optional[
        Dict[str, float]]:
        """Метод взвешенного центра с учетом уверенности измерений."""
        try:
            print("📍 Используем метод взвешенного центра с уверенностью")

            total_weight = 0
            x_sum, y_sum, z_sum = 0, 0, 0

            for anchor_id, data in weighted_measurements.items():
                if anchor_id in self.room_config['anchors']:
                    anchor = self.room_config['anchors'][anchor_id]
                    weight = data['weight']

                    # Учитываем расстояние в весе (близкие якоря имеют больший вес)
                    distance_weight = 1.0 / (data['distance'] + 0.1)

                    # Комбинированный вес
                    combined_weight = weight * distance_weight

                    x_sum += anchor['x'] * combined_weight
                    y_sum += anchor['y'] * combined_weight
                    z_sum += anchor['z'] * combined_weight
                    total_weight += combined_weight

            if total_weight > 0:
                x = x_sum / total_weight
                y = y_sum / total_weight
                z = z_sum / total_weight

                # Интеллектуальная коррекция высоты
                z = self._estimate_enhanced_z_coordinate(x, y, weighted_measurements)

                result = {'x': x, 'y': y, 'z': z}
                print(f"✅ Метод взвешенного центра: {result}")
                return result

            return None

        except Exception as e:
            print(f"Метод взвешенного центра не удался: {e}")
            return None

    def adaptive_geometric_method(self, weighted_measurements: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, float]]:
        """Адаптивный геометрический метод с учетом качества измерений."""
        try:
            print("🔄 Используем адаптивный геометрический метод")

            if len(weighted_measurements) < 2:
                return None

            # Сортируем измерения по уверенности
            sorted_measurements = sorted(
                weighted_measurements.items(),
                key=lambda x: x[1]['weight'],
                reverse=True
            )

            # Используем два наиболее надежных измерения для начальной оценки
            best_measurements = sorted_measurements[:2]

            circles = []
            for anchor_id, data in best_measurements:
                if anchor_id in self.room_config['anchors']:
                    anchor = self.room_config['anchors'][anchor_id]
                    circles.append({
                        'center': (anchor['x'], anchor['y']),
                        'radius': data['distance'],
                        'weight': data['weight']
                    })

            if len(circles) >= 2:
                # Находим точки пересечения двух наиболее надежных окружностей
                intersections = self._find_circle_intersections(
                    circles[0]['center'], circles[0]['radius'],
                    circles[1]['center'], circles[1]['radius']
                )

                if intersections:
                    # Выбираем точку, ближайшую к другим якорям
                    best_point = self._select_best_intersection(intersections, weighted_measurements)
                    z = self._estimate_enhanced_z_coordinate(best_point[0], best_point[1], weighted_measurements)

                    result = {'x': best_point[0], 'y': best_point[1], 'z': z}
                    print(f"✅ Адаптивный геометрический метод: {result}")
                    return result

            return None

        except Exception as e:
            print(f"Адаптивный геометрический метод не удался: {e}")
            return None

    def _estimate_enhanced_z_coordinate(self, x: float, y: float,
                                        weighted_measurements: Dict[str, Dict[str, Any]]) -> float:
        """Улучшенная оценка Z-координаты с учетом качества измерений."""
        try:
            total_weight = 0
            z_weighted = 0

            for anchor_id, data in weighted_measurements.items():
                if anchor_id in self.room_config['anchors']:
                    anchor = self.room_config['anchors'][anchor_id]
                    weight = data['weight']

                    # Учитываем горизонтальное расстояние до якоря
                    horizontal_dist = np.sqrt((x - anchor['x']) ** 2 + (y - anchor['y']) ** 2)
                    distance_ratio = data['distance'] / (horizontal_dist + 0.1)

                    # Оцениваем вертикальную компоненту
                    if data['distance'] > horizontal_dist:
                        z_diff = np.sqrt(data['distance'] ** 2 - horizontal_dist ** 2)
                        estimated_z = anchor['z'] + z_diff
                    else:
                        estimated_z = anchor['z']

                    z_weighted += estimated_z * weight
                    total_weight += weight

            avg_z = z_weighted / total_weight if total_weight > 0 else 1.5

            # Корректируем based на позиции и качестве измерений
            close_to_wall = (x < 2.0 or x > self.room_config['width'] - 2 or
                             y < 2.0 or y > self.room_config['height'] - 2)

            if close_to_wall:
                z_estimate = max(0.3, avg_z * 0.7)
            else:
                z_estimate = min(2.5, max(1.0, avg_z))

            z_estimate = max(0.3, min(3.0, z_estimate))
            print(f"   📊 Улучшенная оценка Z: {z_estimate:.2f}m")
            return z_estimate

        except Exception as e:
            print(f"   ⚠️  Ошибка улучшенной оценки Z: {e}")
            return 1.5

    def _find_circle_intersections(self, center1, radius1, center2, radius2):
        """Находит точки пересечения двух окружностей."""
        x1, y1 = center1
        x2, y2 = center2
        r1, r2 = radius1, radius2

        # Расстояние между центрами
        d = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

        # Проверка возможности пересечения
        if d > r1 + r2 or d < abs(r1 - r2):
            return None

        # Вычисления точек пересечения
        a = (r1 ** 2 - r2 ** 2 + d ** 2) / (2 * d)
        h = np.sqrt(r1 ** 2 - a ** 2)

        xm = x1 + a * (x2 - x1) / d
        ym = y1 + a * (y2 - y1) / d

        xs1 = xm + h * (y2 - y1) / d
        xs2 = xm - h * (y2 - y1) / d
        ys1 = ym - h * (x2 - x1) / d
        ys2 = ym + h * (x2 - x1) / d

        return [(xs1, ys1), (xs2, ys2)]

    def _select_best_intersection(self, intersections, weighted_measurements):
        """Выбирает лучшую точку пересечения на основе других измерений."""
        if len(intersections) == 1:
            return intersections[0]

        # Оцениваем каждую точку пересечения
        best_score = float('inf')
        best_point = intersections[0]

        for point in intersections:
            score = 0
            for anchor_id, data in weighted_measurements.items():
                if anchor_id in self.room_config['anchors']:
                    anchor = self.room_config['anchors'][anchor_id]
                    calculated_dist = np.sqrt(
                        (point[0] - anchor['x']) ** 2 +
                        (point[1] - anchor['y']) ** 2
                    )
                    error = abs(calculated_dist - data['distance'])
                    score += error * data['weight']

            if score < best_score:
                best_score = score
                best_point = point

        return best_point

    def is_valid_position(self, position: Dict[str, float]) -> bool:
        """Проверяет, что позиция находится в пределах комнаты."""
        x, y, z = position['x'], position['y'], position['z']
        valid = (0 <= x <= self.room_config['width'] and
                 0 <= y <= self.room_config['height'] and
                 0 <= z <= 4.0)

        if not valid:
            print(f"⚠️  Позиция вне комнаты: ({x:.2f}, {y:.2f}, {z:.2f})")

        return valid

    def correct_position(self, position: Dict[str, float]) -> Dict[str, float]:
        """Корректирует позицию чтобы она была внутри комнаты."""
        x = max(0.5, min(self.room_config['width'] - 0.5, position['x']))
        y = max(0.5, min(self.room_config['height'] - 0.5, position['y']))
        z = max(0.5, min(3.0, position['z']))

        corrected = {'x': x, 'y': y, 'z': z}
        print(f"   📍 Скорректированная позиция: {corrected}")
        return corrected


def calculate_enhanced_confidence(weighted_measurements: Dict[str, Dict[str, Any]],
                                  position: Dict[str, float]) -> float:
    """Улучшенный расчет уверенности с учетом расширенных данных."""
    try:
        # Базовая уверенность по количеству якорей
        anchor_count = len(weighted_measurements)
        anchor_confidence = min(1.0, anchor_count / 4.0)

        # Уверенность по согласованности измерений
        total_error = 0
        total_weight = 0

        for anchor_id, data in weighted_measurements.items():
            if anchor_id in weighted_measurements:
                anchor_data = weighted_measurements[anchor_id]
                if 'original_data' in anchor_data:
                    anchor = anchor_data['original_data']
                    calculated_dist = np.sqrt(
                        (position['x'] - anchor['x']) ** 2 +
                        (position['y'] - anchor['y']) ** 2 +
                        (position['z'] - anchor['z']) ** 2
                    )
                    error = abs(calculated_dist - anchor['distance'])
                    total_error += error * anchor_data['weight']
                    total_weight += anchor_data['weight']

        consistency_confidence = 1.0 - (total_error / (total_weight + 0.1)) / 5.0

        # Уверенность по качеству данных
        avg_confidence = np.mean([data['confidence'] for data in weighted_measurements.values()])

        # Общая уверенность
        total_confidence = (anchor_confidence * 0.3 +
                            consistency_confidence * 0.4 +
                            avg_confidence * 0.3)

        return max(0.1, min(1.0, total_confidence))

    except Exception as e:
        print(f"Ошибка расчета улучшенной уверенности: {e}")
        return 0.5