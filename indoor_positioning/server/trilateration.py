"""
Indoor Positioning System - Positioning Evaluations Module

Этот модуль реализует вычисления для позиционирования в помещении.
Обрабатывает данные от ESP32 якорей и вычисляет позиции устройств
"""

import numpy as np
import logging
from typing import Dict, List, Tuple, Optional, Any

logger = logging.getLogger(__name__)


class TrilaterationEngine:
    """Движок для расчета позиции в 3D-пространстве методом трилатерации."""

    def __init__(self, room_config: Dict[str, Any]) -> None:
        self.room_config = room_config

    def update_room_config(self, room_config: Dict[str, Any]) -> None:
        """Обновляет конфигурацию комнаты и якорей."""
        self.room_config = room_config
        print(f"🔄 Trilateration engine updated: room {room_config['width']}x{room_config['height']}, {len(room_config['anchors'])} anchors")

    def calculate_position(self, anchor_distances: Dict[str, float]) -> Optional[Dict[str, float]]:
        """Основная функция расчета позиции с автоматическим выбором метода."""
        try:
            if len(anchor_distances) < 2:
                return None

            print(f"🎯 Начало расчета позиции для {len(anchor_distances)} якорей")

            # Пробуем последовательно разные методы
            position = self.trilateration_3d(anchor_distances)
            if not position or not self.is_valid_position(position):
                position = self.trilateration_2d_plus(anchor_distances)
            if not position or not self.is_valid_position(position):
                position = self.simple_geometric_method_3d(anchor_distances)
            if position and not self.is_valid_position(position):
                position = self.correct_position(position)

            return position

        except Exception as e:
            logger.error(f"Ошибка расчета позиции: {e}")
            return None

    def trilateration_3d(self, anchor_distances: Dict[str, float]) -> Optional[Dict[str, float]]:
        """3D трилатерация методом наименьших квадратов (требуется минимум 3 якоря)."""
        try:
            anchors_list, distances_list = self._prepare_anchor_data(anchor_distances)

            if len(anchors_list) < 3:
                return None

            # Проверяем достаточность вариации высот для 3D расчета
            z_coords = [anchor[2] for anchor in anchors_list]
            z_variation = max(z_coords) - min(z_coords)

            if z_variation < 0.5:
                print(f"⚠️  Малая вариация высот ({z_variation:.2f}m), используем 2D+ трилатерацию")
                return None

            print("📍 Используем 3D трилатерацию")
            A_linear, b = self._build_linear_system_3d(anchors_list, distances_list)

            if np.linalg.matrix_rank(A_linear) < 3:
                print("⚠️  3D матрица вырождена")
                return None

            position = np.linalg.lstsq(A_linear, b, rcond=None)[0]

            if np.any(np.isnan(position)):
                return None

            result = {
                'x': float(position[0]),
                'y': float(position[1]),
                'z': float(position[2])
            }

            print(f"✅ Успешная 3D трилатерация: {result}")
            return result

        except Exception as e:
            logger.debug(f"3D трилатерация не удалась: {e}")
            return None

    def trilateration_2d_plus(self, anchor_distances: Dict[str, float]) -> Optional[Dict[str, float]]:
        """2D трилатерация с интеллектуальной оценкой Z-координаты."""
        try:
            anchors_list, distances_list = self._prepare_anchor_data(anchor_distances, use_2d=True)

            if len(anchors_list) < 3:
                return None

            print("📍 Используем 2D+ трилатерацию")
            A, b = self._build_linear_system_2d(anchors_list, distances_list)

            if np.linalg.matrix_rank(A) < 2:
                print("❌ 2D матрица также вырождена")
                return None

            position_2d = np.linalg.lstsq(A, b, rcond=None)[0]

            if np.any(np.isnan(position_2d)):
                return None

            z_coordinate = self._estimate_smart_z_coordinate(position_2d[0], position_2d[1], anchor_distances)

            result = {
                'x': float(position_2d[0]),
                'y': float(position_2d[1]),
                'z': float(z_coordinate)
            }

            print(f"✅ Успешная 2D+ трилатерация: {result}")
            return result

        except Exception as e:
            logger.debug(f"2D+ трилатерация не удалась: {e}")
            return None

    def simple_geometric_method_3d(self, anchor_distances: Dict[str, float]) -> Optional[Dict[str, float]]:
        """Упрощенный геометрический метод расчета 3D позиции (резервный метод)."""
        try:
            print("🔄 Используем упрощенный 3D геометрический метод")

            anchors_info = []
            for anchor_id, distance in anchor_distances.items():
                if anchor_id in self.room_config['anchors']:
                    anchor = self.room_config['anchors'][anchor_id]
                    anchors_info.append({
                        'x': anchor['x'], 'y': anchor['y'], 'z': anchor['z'],
                        'distance': distance
                    })

            if len(anchors_info) < 2:
                return None

            # Метод взвешенного центра
            total_weight = 0
            x_sum, y_sum, z_sum = 0, 0, 0

            for anchor in anchors_info:
                weight = 1.0 / (anchor['distance'] ** 2 + 0.1)
                x_sum += anchor['x'] * weight
                y_sum += anchor['y'] * weight
                z_sum += anchor['z'] * weight
                total_weight += weight

            if total_weight > 0:
                x = x_sum / total_weight
                y = y_sum / total_weight
                z = z_sum / total_weight
                z = self._estimate_smart_z_coordinate(x, y, anchor_distances)

                result = {'x': x, 'y': y, 'z': z}
                print(f"✅ Упрощенный 3D метод: {result}")
                return result

            return None

        except Exception as e:
            logger.debug(f"Геометрический метод не удался: {e}")
            return {'x': 10.0, 'y': 7.5, 'z': 1.5}  # Fallback позиция

    def _prepare_anchor_data(self, anchor_distances: Dict[str, float], use_2d: bool = False) -> Tuple[
        List[List[float]], List[float]]:
        """Подготавливает данные якорей для трилатерации."""
        anchors_list = []
        distances_list = []

        for anchor_id, distance in anchor_distances.items():
            if anchor_id in self.room_config['anchors']:
                anchor = self.room_config['anchors'][anchor_id]
                if use_2d:
                    anchors_list.append([anchor['x'], anchor['y']])
                else:
                    anchors_list.append([anchor['x'], anchor['y'], anchor['z']])
                distances_list.append(distance)
                print(f"📍 Якорь {anchor_id}: ({anchor['x']}, {anchor['y']}, {anchor['z']}) -> {distance}m")

        return anchors_list, distances_list

    def _build_linear_system_3d(self, anchors_list: List[List[float]], distances_list: List[float]) -> Tuple[
        np.ndarray, np.ndarray]:
        """Строит линейную систему уравнений для 3D трилатерации."""
        A_linear = []
        b = []

        for i in range(1, len(anchors_list)):
            xi, yi, zi = anchors_list[i]
            x0, y0, z0 = anchors_list[0]
            di = distances_list[i]
            d0 = distances_list[0]

            A_i = [2 * (xi - x0), 2 * (yi - y0), 2 * (zi - z0)]
            b_i = (di ** 2 - d0 ** 2 - xi ** 2 + x0 ** 2 - yi ** 2 + y0 ** 2 - zi ** 2 + z0 ** 2)

            A_linear.append(A_i)
            b.append(b_i)

        return np.array(A_linear), np.array(b)

    def _build_linear_system_2d(self, anchors_list: List[List[float]], distances_list: List[float]) -> Tuple[
        np.ndarray, np.ndarray]:
        """Строит линейную систему уравнений для 2D трилатерации."""
        A = []
        b = []

        for i in range(1, len(anchors_list)):
            xi, yi = anchors_list[i]
            x0, y0 = anchors_list[0]
            di = distances_list[i]
            d0 = distances_list[0]

            A_i = [2 * (xi - x0), 2 * (yi - y0)]
            b_i = (di ** 2 - d0 ** 2 - xi ** 2 + x0 ** 2 - yi ** 2 + y0 ** 2)

            A.append(A_i)
            b.append(b_i)

        return np.array(A), np.array(b)

    def _estimate_smart_z_coordinate(self, x: float, y: float, anchor_distances: Dict[str, float]) -> float:
        """Интеллектуальная оценка Z-координаты на основе контекста."""
        try:
            anchors_info = []
            for anchor_id, distance in anchor_distances.items():
                if anchor_id in self.room_config['anchors']:
                    anchor = self.room_config['anchors'][anchor_id]
                    anchors_info.append({
                        'z': anchor['z'], 'distance': distance
                    })

            # Средневзвешенная высота
            total_weight, z_weighted = 0, 0
            for anchor in anchors_info:
                weight = 1.0 / (anchor['distance'] + 0.1)
                z_weighted += anchor['z'] * weight
                total_weight += weight

            avg_z = z_weighted / total_weight if total_weight > 0 else 1.5

            # Корректируем based на позиции (близость к стенам)
            close_to_wall = (x < 2.0 or x > self.room_config['width'] - 2 or
                             y < 2.0 or y > self.room_config['height'] - 2)

            if close_to_wall:
                z_estimate = max(0.3, avg_z * 0.7)
            else:
                z_estimate = min(2.5, max(1.0, avg_z))

            z_estimate = max(0.3, min(3.0, z_estimate))
            print(f"   📊 Умная оценка Z: {z_estimate:.2f}m (среднее: {avg_z:.2f}m)")
            return z_estimate

        except Exception as e:
            print(f"   ⚠️  Ошибка оценки Z, используем значение по умолчанию: {e}")
            return 1.5

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


def calculate_confidence(anchor_distances: Dict[str, float], position: Dict[str, float]) -> float:
    """Вычисляет уверенность в расчете позиции на основе дисперсии расстояний и количества якорей."""
    try:
        variance = np.var(list(anchor_distances.values()))
        confidence = max(0.1, 1.0 - variance / 10.0)
        anchor_count = len(anchor_distances)
        confidence *= min(1.0, anchor_count / 4.0)
        return round(confidence, 2)
    except:
        return 0.5