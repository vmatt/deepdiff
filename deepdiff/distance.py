import datetime
from deepdiff.deephash import DeepHash
from deepdiff.helper import (
    DELTA_VIEW, numbers, strings, add_to_frozen_set, not_found, only_numbers, np, np_float64, time_to_seconds,
    cartesian_product_numpy, np_ndarray, np_array_factory, get_homogeneous_numpy_compatible_type_of_seq, dict_,
    CannotCompare)
from collections.abc import Mapping, Iterable


DISTANCE_CALCS_NEEDS_CACHE = "Distance calculation can not happen once the cache is purged. Try with _cache='keep'"


class DistanceMixin:

    def _get_rough_distance(self):
        """
        Gives a numeric value for the distance of t1 and t2 based on how many operations are needed to convert
        one to the other.

        This is a similar concept to the Levenshtein Edit Distance but for the structured data and is it is designed
        to be between 0 and 1.

        A distance of zero means the objects are equal and a distance of 1 is very far.

        Note: The distance calculation formula is subject to change in future. Use the distance results only as a
        way of comparing the distances of pairs of items with other pairs rather than an absolute distance
        such as the one provided by Levenshtein edit distance.

        Info: The current algorithm is based on the number of operations that are needed to convert t1 to t2 divided
        by the number of items that make up t1 and t2.
        """

        _distance = get_numeric_types_distance(
            self.t1, self.t2, max_=self.cutoff_distance_for_pairs)

        if _distance is not not_found:
            return _distance

        item = self if self.view == DELTA_VIEW else self._to_delta_dict(report_repetition_required=False)
        diff_length = _get_item_length(item)

        if diff_length == 0:
            return 0

        t1_len = self.__get_item_rough_length(self.t1)
        t2_len = self.__get_item_rough_length(self.t2)

        return diff_length / (t1_len + t2_len)

    def __get_item_rough_length(self, item, parent='root'):
        """
        Get the rough length of an item.
        It is used as a part of calculating the rough distance between objects.

        **parameters**

        item: The item to calculate the rough length for
        parent: It is only used for DeepHash reporting purposes. Not really useful here.
        """
        if not hasattr(self, 'hashes'):
            raise RuntimeError(DISTANCE_CALCS_NEEDS_CACHE)
        length = DeepHash.get_key(self.hashes, key=item, default=None, extract_index=1)
        if length is None:
            self.__calculate_item_deephash(item)
            length = DeepHash.get_key(self.hashes, key=item, default=None, extract_index=1)
        return length

    def __calculate_item_deephash(self, item):
        DeepHash(
            item,
            hashes=self.hashes,
            parent='root',
            apply_hash=True,
            **self.deephash_parameters,
        )

    def _precalculate_distance_by_custom_compare_func(
            self, hashes_added, hashes_removed, t1_hashtable, t2_hashtable, _original_type):

        pre_calced_distances = dict_()
        for added_hash in hashes_added:
            for removed_hash in hashes_removed:
                try:
                    is_close_distance = self.iterable_compare_func(t2_hashtable[added_hash].item, t1_hashtable[removed_hash].item)
                except CannotCompare:
                    pass
                else:
                    if is_close_distance:
                        # an arbitrary small distance if math_epsilon is not defined
                        distance = self.math_epsilon or 0.000001
                    else:
                        distance = 1
                    pre_calced_distances["{}--{}".format(added_hash, removed_hash)] = distance

        return pre_calced_distances

    def _precalculate_numpy_arrays_distance(
            self, hashes_added, hashes_removed, t1_hashtable, t2_hashtable, _original_type):

        # We only want to deal with 1D arrays.
        if isinstance(t2_hashtable[hashes_added[0]].item, (np_ndarray, list)):
            return

        pre_calced_distances = dict_()
        added = [t2_hashtable[k].item for k in hashes_added]
        removed = [t1_hashtable[k].item for k in hashes_removed]

        if _original_type is None:
            added_numpy_compatible_type = get_homogeneous_numpy_compatible_type_of_seq(added)
            removed_numpy_compatible_type = get_homogeneous_numpy_compatible_type_of_seq(removed)
            if added_numpy_compatible_type and added_numpy_compatible_type == removed_numpy_compatible_type:
                _original_type = added_numpy_compatible_type
        if _original_type is None:
            return

        added = np_array_factory(added, dtype=_original_type)
        removed = np_array_factory(removed, dtype=_original_type)

        pairs = cartesian_product_numpy(added, removed)

        pairs_transposed = pairs.T

        distances = _get_numpy_array_distance(
            pairs_transposed[0], pairs_transposed[1],
            max_=self.cutoff_distance_for_pairs)

        i = 0
        for added_hash in hashes_added:
            for removed_hash in hashes_removed:
                pre_calced_distances["{}--{}".format(added_hash, removed_hash)] = distances[i]
                i += 1
        return pre_calced_distances


def _get_item_length(item, parents_ids=frozenset([])):
    """
    Get the number of operations in a diff object.
    It is designed mainly for the delta view output
    but can be used with other dictionary types of view outputs too.
    """
    length = 0
    if isinstance(item, Mapping):
        for key, subitem in item.items():
            # dedupe the repetition report so the number of times items have shown up does not affect the distance.
            if key in {'iterable_items_added_at_indexes', 'iterable_items_removed_at_indexes'}:
                new_subitem = dict_()
                for path_, indexes_to_items in subitem.items():
                    used_value_ids = set()
                    new_indexes_to_items = dict_()
                    for k, v in indexes_to_items.items():
                        v_id = id(v)
                        if v_id not in used_value_ids:
                            used_value_ids.add(v_id)
                            new_indexes_to_items[k] = v
                    new_subitem[path_] = new_indexes_to_items
                subitem = new_subitem

            # internal keys such as _numpy_paths should not count towards the distance
            if isinstance(key, strings) and (key.startswith('_') or key == 'deep_distance' or key == 'new_path'):
                continue

            item_id = id(subitem)
            if parents_ids and item_id in parents_ids:
                continue
            parents_ids_added = add_to_frozen_set(parents_ids, item_id)
            length += _get_item_length(subitem, parents_ids_added)
    elif isinstance(item, numbers):
        length = 1
    elif isinstance(item, strings):
        length = 1
    elif isinstance(item, Iterable):
        for subitem in item:
            item_id = id(subitem)
            if parents_ids and item_id in parents_ids:
                continue
            parents_ids_added = add_to_frozen_set(parents_ids, item_id)
            length += _get_item_length(subitem, parents_ids_added)
    elif isinstance(item, type):  # it is a class
        length = 1
    else:
        if hasattr(item, '__dict__'):
            for subitem in item.__dict__:
                item_id = id(subitem)
                parents_ids_added = add_to_frozen_set(parents_ids, item_id)
                length += _get_item_length(subitem, parents_ids_added)
    return length


def _get_numbers_distance(num1, num2, max_=1):
    """
    Get the distance of 2 numbers. The output is a number between 0 to the max.
    The reason is the
    When max is returned means the 2 numbers are really far, and 0 means they are equal.
    """
    if num1 == num2:
        return 0
    if not isinstance(num1, float):
        num1 = float(num1)
    if not isinstance(num2, float):
        num2 = float(num2)
    # Since we have a default cutoff of 0.3 distance when
    # getting the pairs of items during the ingore_order=True
    # calculations, we need to make the divisor of comparison very big
    # so that any 2 numbers can be chosen as pairs.
    divisor = (num1 + num2) / max_
    if divisor == 0:
        return max_
    try:
        return min(max_, abs((num1 - num2) / divisor))
    except Exception:  # pragma: no cover. I don't think this line will ever run but doesn't hurt to leave it.
        return max_  # pragma: no cover


def _numpy_div(a, b, replace_inf_with=1):
    max_array = np.full(shape=a.shape, fill_value=replace_inf_with, dtype=np_float64)
    result = np.divide(a, b, out=max_array, where=b != 0, dtype=np_float64)
    # wherever 2 numbers are the same, make sure the distance is zero. This is mainly for 0 divided by zero.
    result[a == b] = 0
    return result


def _get_numpy_array_distance(num1, num2, max_=1):
    """
    Get the distance of 2 numbers. The output is a number between 0 to the max.
    The reason is the
    When max is returned means the 2 numbers are really far, and 0 means they are equal.
    """
    # Since we have a default cutoff of 0.3 distance when
    # getting the pairs of items during the ingore_order=True
    # calculations, we need to make the divisor of comparison very big
    # so that any 2 numbers can be chosen as pairs.
    divisor = (num1 + num2) / max_
    result = _numpy_div((num1 - num2), divisor, replace_inf_with=max_)
    return np.clip(np.absolute(result), 0, max_)


def _get_datetime_distance(date1, date2, max_):
    return _get_numbers_distance(date1.timestamp(), date2.timestamp(), max_)


def _get_date_distance(date1, date2, max_):
    return _get_numbers_distance(date1.toordinal(), date2.toordinal(), max_)


def _get_timedelta_distance(timedelta1, timedelta2, max_):
    return _get_numbers_distance(timedelta1.total_seconds(), timedelta2.total_seconds(), max_)


def _get_time_distance(time1, time2, max_):
    return _get_numbers_distance(time_to_seconds(time1), time_to_seconds(time2), max_)


TYPES_TO_DIST_FUNC = [
    (only_numbers, _get_numbers_distance),
    (datetime.datetime, _get_datetime_distance),
    (datetime.date, _get_date_distance),
    (datetime.timedelta, _get_timedelta_distance),
    (datetime.time, _get_time_distance),
]


def get_numeric_types_distance(num1, num2, max_):
    for type_, func in TYPES_TO_DIST_FUNC:
        if isinstance(num1, type_) and isinstance(num2, type_):
            return func(num1, num2, max_)
    return not_found
