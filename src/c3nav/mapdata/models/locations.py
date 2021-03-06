import string
from contextlib import suppress
from datetime import timedelta
from decimal import Decimal
from operator import attrgetter

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import FieldDoesNotExist, Prefetch
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.functional import cached_property
from django.utils.text import format_lazy
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.base import SerializableMixin, TitledMixin
from c3nav.mapdata.utils.fields import LocationById
from c3nav.mapdata.utils.models import get_submodels


class LocationSlugManager(models.Manager):
    def get_queryset(self):
        result = super().get_queryset()
        if self.model == LocationSlug:
            for model in get_submodels(Location) + [LocationRedirect]:
                result = result.select_related(model._meta.default_related_name)
                try:
                    model._meta.get_field('space')
                except FieldDoesNotExist:
                    pass
                else:
                    result = result.select_related(model._meta.default_related_name+'__space')
        return result

    def select_related_target(self):
        if self.model != LocationSlug:
            raise TypeError
        qs = self.get_queryset()
        qs = qs.select_related('redirect__target', *('redirect__target__'+model._meta.default_related_name
                                                     for model in get_submodels(Location) + [LocationRedirect]))
        return qs


validate_slug = RegexValidator(
    r'^[a-z0-9]+(--?[a-z0-9]+)*\Z',
    # Translators: "letters" means latin letters: a-z and A-Z.
    _('Enter a valid location slug consisting of lowercase letters, numbers or hyphens, '
      'not starting or ending with hyphens or containing consecutive hyphens.'),
    'invalid'
)


class LocationSlug(SerializableMixin, models.Model):
    LOCATION_TYPE_CODES = {
        'Level': 'l',
        'Space': 's',
        'Area': 'a',
        'POI': 'p',
        'LocationGroup': 'g'
    }
    LOCATION_TYPE_BY_CODE = {code: model_name for model_name, code in LOCATION_TYPE_CODES.items()}
    slug = models.SlugField(_('Slug'), unique=True, null=True, blank=True, max_length=50, validators=[validate_slug])

    objects = LocationSlugManager()

    def get_child(self, instance=None):
        for model in get_submodels(Location)+[LocationRedirect]:
            with suppress(AttributeError):
                return getattr(instance or self, model._meta.default_related_name)
        return None

    def get_slug(self):
        return self.slug

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        result['slug'] = self.get_slug()
        return result

    def details_display(self, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].insert(2, (_('Slug'), str(self.get_slug())))
        return result

    @cached_property
    def order(self):
        return (-1, 0)

    class Meta:
        verbose_name = _('Location with Slug')
        verbose_name_plural = _('Location with Slug')
        default_related_name = 'locationslugs'


class Location(LocationSlug, AccessRestrictionMixin, TitledMixin, models.Model):
    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can describe'))
    icon = models.CharField(_('icon'), max_length=32, null=True, blank=True, help_text=_('any material icons name'))

    class Meta:
        abstract = True

    def serialize(self, detailed=True, describe_only=False, **kwargs):
        result = super().serialize(detailed=detailed, **kwargs)
        if not detailed:
            fields = ('id', 'type', 'slug', 'title', 'subtitle', 'icon', 'point', 'bounds', 'grid_square',
                      'locations', 'on_top_of', 'label_settings', 'label_override', 'add_search', 'dynamic')
            result = {name: result[name] for name in fields if name in result}
        return result

    def _serialize(self, search=False, **kwargs):
        result = super()._serialize(**kwargs)
        result['subtitle'] = str(self.subtitle)
        result['icon'] = self.get_icon()
        result['can_search'] = self.can_search
        result['can_describe'] = self.can_search
        if search:
            result['add_search'] = ' '.join((
                *(redirect.slug for redirect in self.redirects.all()),
                *self.other_titles,
            ))
        return result

    def details_display(self, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].extend([
            (_('searchable'), _('Yes') if self.can_search else _('No')),
            (_('can describe'), _('Yes') if self.can_describe else _('No')),
            (_('icon'), self.get_icon()),
        ])
        return result

    def get_slug(self):
        if self.slug is None:
            code = self.LOCATION_TYPE_CODES.get(self.__class__.__name__)
            if code is not None:
                return code+':'+str(self.id)
        return self.slug

    @property
    def subtitle(self):
        return ''

    @property
    def grid_square(self):
        return None

    def get_color(self, instance=None):
        # dont filter in the query here so prefetch_related works
        result = self.get_color_sorted(instance)
        return None if result is None else result[1]

    def get_color_sorted(self, instance=None):
        # dont filter in the query here so prefetch_related works
        if instance is None:
            instance = self
        for group in instance.groups.all():
            if group.color and getattr(group.category, 'allow_'+self.__class__._meta.default_related_name):
                return (0, group.category.priority, group.hierarchy, group.priority), group.color
        return None

    def get_icon(self):
        return self.icon or None


class SpecificLocation(Location, models.Model):
    groups = models.ManyToManyField('mapdata.LocationGroup', verbose_name=_('Location Groups'), blank=True)
    label_settings = models.ForeignKey('mapdata.LabelSettings', null=True, blank=True, on_delete=models.PROTECT,
                                       verbose_name=_('label settings'))
    label_override = I18nField(_('Label override'), plural_name='label_overrides', blank=True, fallback_any=True)

    class Meta:
        abstract = True

    def _serialize(self, detailed=True, **kwargs):
        result = super()._serialize(detailed=detailed, **kwargs)
        if grid.enabled:
            grid_square = self.grid_square
            if grid_square is not None:
                result['grid_square'] = grid_square or None
        if detailed:
            groups = {}
            for group in self.groups.all():
                groups.setdefault(group.category, []).append(group.pk)
            groups = {category.name: (items[0] if items else None) if category.single else items
                      for category, items in groups.items()
                      if getattr(category, 'allow_'+self.__class__._meta.default_related_name)}
            result['groups'] = groups

        label_settings = self.get_label_settings()
        if label_settings:
            result['label_settings'] = label_settings.serialize(detailed=False)
        if self.label_overrides:
            # todo: what if only one language is set?
            result['label_override'] = self.label_override
        return result

    def get_label_settings(self):
        if self.label_settings:
            return self.label_settings
        for group in self.groups.all():
            if group.label_settings:
                return group.label_settings
        return None

    def details_display(self, **kwargs):
        result = super().details_display(**kwargs)

        groupcategories = {}
        for group in self.groups.all():
            groupcategories.setdefault(group.category, []).append(group)

        if grid.enabled:
            grid_square = self.grid_square
            if grid_square is not None:
                grid_square_title = (_('Grid Squares') if grid_square and '-' in grid_square else _('Grid Square'))
                result['display'].insert(3, (grid_square_title, grid_square or None))

        for category, groups in sorted(groupcategories.items(), key=lambda item: item[0].priority):
            result['display'].insert(3, (
                category.title if category.single else category.title_plural,
                tuple({
                    'id': group.pk,
                    'slug': group.get_slug(),
                    'title': group.title,
                    'can_search': group.can_search,
                } for group in sorted(groups, key=attrgetter('priority'), reverse=True))
            ))

        return result

    @cached_property
    def describing_groups(self):
        groups = tuple(self.groups.all() if 'groups' in getattr(self, '_prefetched_objects_cache', ()) else ())
        groups = tuple(group for group in groups if group.can_describe)
        return groups

    @property
    def subtitle(self):
        subtitle = self.describing_groups[0].title if self.describing_groups else self.__class__._meta.verbose_name
        if self.grid_square:
            return '%s, %s' % (subtitle, self.grid_square)
        return subtitle

    @cached_property
    def order(self):
        groups = tuple(self.groups.all())
        if not groups:
            return (0, 0, 0)
        return (0, groups[0].category.priority, groups[0].priority)

    def get_icon(self):
        icon = super().get_icon()
        if icon:
            return icon
        for group in self.groups.all():
            if group.icon and getattr(group.category, 'allow_' + self.__class__._meta.default_related_name):
                return group.icon
        return None


class LocationGroupCategory(SerializableMixin, models.Model):
    name = models.SlugField(_('Name'), unique=True, max_length=50)
    single = models.BooleanField(_('single selection'), default=False)
    title = I18nField(_('Title'), plural_name='titles', fallback_any=True)
    title_plural = I18nField(_('Title (Plural)'), plural_name='titles_plural', fallback_any=True)
    help_text = I18nField(_('Help text'), plural_name='help_texts', fallback_any=True, fallback_value='')
    allow_levels = models.BooleanField(_('allow levels'), db_index=True, default=True)
    allow_spaces = models.BooleanField(_('allow spaces'), db_index=True, default=True)
    allow_areas = models.BooleanField(_('allow areas'), db_index=True, default=True)
    allow_pois = models.BooleanField(_('allow pois'), db_index=True, default=True)
    allow_dynamic_locations = models.BooleanField(_('allow dynamic locations'), db_index=True, default=True)
    priority = models.IntegerField(default=0, db_index=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.orig_priority = self.priority

    class Meta:
        verbose_name = _('Location Group Category')
        verbose_name_plural = _('Location Group Categories')
        default_related_name = 'locationgroupcategories'
        ordering = ('-priority', )

    def _serialize(self, detailed=True, **kwargs):
        result = super()._serialize(detailed=detailed, **kwargs)
        result['name'] = self.name
        if detailed:
            result['titles'] = self.titles
        result['title'] = self.title
        return result

    def register_changed_geometries(self):
        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
        query = self.groups.all()
        for model in get_submodels(SpecificLocation):
            related_name = model._meta.default_related_name
            subquery = model.objects.all()
            if issubclass(model, SpaceGeometryMixin):
                subquery = subquery.select_related('space')
            query.prefetch_related(Prefetch('groups__'+related_name, subquery))

        for group in query:
            group.register_changed_geometries(do_query=False)

    def save(self, *args, **kwargs):
        if self.pk and self.priority != self.orig_priority:
            self.register_changed_geometries()
        super().save(*args, **kwargs)


class LocationGroupManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('category')


class LocationGroup(Location, models.Model):
    category = models.ForeignKey(LocationGroupCategory, related_name='groups', on_delete=models.PROTECT,
                                 verbose_name=_('Category'))
    priority = models.IntegerField(default=0, db_index=True)
    hierarchy = models.IntegerField(default=0, db_index=True, verbose_name=_('hierarchy'))
    label_settings = models.ForeignKey('mapdata.LabelSettings', null=True, blank=True, on_delete=models.PROTECT,
                                       verbose_name=_('label settings'),
                                       help_text=_('unless location specifies otherwise'))
    can_report_missing = models.BooleanField(default=False, verbose_name=_('for missing locations'),
                                             help_text=_('can be used when reporting a missing location'))
    color = models.CharField(null=True, blank=True, max_length=32, verbose_name=_('background color'))

    objects = LocationGroupManager()

    class Meta:
        verbose_name = _('Location Group')
        verbose_name_plural = _('Location Groups')
        default_related_name = 'locationgroups'
        ordering = ('-category__priority', '-priority')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.orig_priority = self.priority
        self.orig_hierarchy = self.hierarchy
        self.orig_category_id = self.category_id
        self.orig_color = self.color

    def _serialize(self, simple_geometry=False, **kwargs):
        result = super()._serialize(simple_geometry=simple_geometry, **kwargs)
        result['category'] = self.category_id
        result['color'] = self.color
        if simple_geometry:
            result['locations'] = tuple(obj.pk for obj in getattr(self, 'locations', ()))
        return result

    def details_display(self, editor_url=True, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].insert(3, (_('Category'), self.category.title))
        result['display'].extend([
            (_('color'), self.color),
            (_('priority'), self.priority),
        ])
        if editor_url:
            result['editor_url'] = reverse('editor.locationgroups.edit', kwargs={'pk': self.pk})
        return result

    @property
    def title_for_forms(self):
        attributes = []
        if self.can_search:
            attributes.append(_('search'))
        if self.can_describe:
            attributes.append(_('describe'))
        if self.color:
            attributes.append(_('color'))
        if not attributes:
            attributes.append(_('internal'))
        return self.title + ' ('+', '.join(str(s) for s in attributes)+')'

    def register_changed_geometries(self, do_query=True):
        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
        for model in get_submodels(SpecificLocation):
            query = getattr(self, model._meta.default_related_name).all()
            if do_query:
                if issubclass(model, SpaceGeometryMixin):
                    query = query.select_related('space')
            for obj in query:
                obj.register_change(force=True)

    @property
    def subtitle(self):
        result = self.category.title
        if hasattr(self, 'locations'):
            return format_lazy(_('{category_title}, {num_locations}'),
                               category_title=result,
                               num_locations=(ungettext_lazy('%(num)d location', '%(num)d locations', 'num') %
                                              {'num': len(self.locations)}))
        return result

    @cached_property
    def order(self):
        return (1, self.category.priority, self.priority)

    def save(self, *args, **kwargs):
        if self.pk and (self.orig_color != self.color or
                        self.priority != self.orig_priority or
                        self.hierarchy != self.orig_hierarchy or
                        self.category_id != self.orig_category_id):
            self.register_changed_geometries()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.register_changed_geometries()
        super().delete(*args, **kwargs)


class LocationRedirect(LocationSlug):
    target = models.ForeignKey(LocationSlug, related_name='redirects', on_delete=models.CASCADE,
                               verbose_name=_('target'))

    def _serialize(self, include_type=True, **kwargs):
        result = super()._serialize(include_type=include_type, **kwargs)
        if type(self.target) == LocationSlug:
            result['target'] = self.target.get_child().slug
        else:
            result['target'] = self.target.slug
        if include_type:
            result['type'] = 'redirect'
        result.pop('id')
        return result

    class Meta:
        default_related_name = 'redirect'


class LabelSettings(SerializableMixin, models.Model):
    title = I18nField(_('Title'), plural_name='titles', fallback_any=True)
    min_zoom = models.DecimalField(_('min zoom'), max_digits=3, decimal_places=1, default=-10,
                                   validators=[MinValueValidator(Decimal('-10')),
                                               MaxValueValidator(Decimal('10'))])
    max_zoom = models.DecimalField(_('max zoom'), max_digits=3, decimal_places=1, default=10,
                                   validators=[MinValueValidator(Decimal('-10')),
                                               MaxValueValidator(Decimal('10'))])
    font_size = models.IntegerField(_('font size'), default=12,
                                    validators=[MinValueValidator(12),
                                                MaxValueValidator(30)])

    def _serialize(self, detailed=True, **kwargs):
        result = super()._serialize(detailed=detailed, **kwargs)
        if detailed:
            result['titles'] = self.titles
        if self.min_zoom > -10:
            result['min_zoom'] = self.min_zoom
        if self.max_zoom < 10:
            result['max_zoom'] = self.max_zoom
        result['font_size'] = self.font_size
        return result

    class Meta:
        verbose_name = _('Label Settings')
        verbose_name_plural = _('Label Settings')
        default_related_name = 'labelsettings'
        ordering = ('min_zoom', '-font_size')


class CustomLocationProxyMixin:
    def get_custom_location(self):
        raise NotImplementedError

    @property
    def available(self):
        return self.get_custom_location() is not None

    @property
    def x(self):
        return self.get_custom_location().x

    @property
    def y(self):
        return self.get_custom_location().y

    @property
    def level(self):
        return self.get_custom_location().level

    def serialize_position(self):
        raise NotImplementedError


class DynamicLocation(CustomLocationProxyMixin, SpecificLocation, models.Model):
    position_secret = models.CharField(_('position secret'), max_length=32, null=True, blank=True)

    class Meta:
        verbose_name = _('Dynamic location')
        verbose_name_plural = _('Dynamic locations')
        default_related_name = 'dynamic_locations'

    def _serialize(self, **kwargs):
        """custom_location = self.get_custom_location()
        print(custom_location)
        result = {} if custom_location is None else custom_location.serialize(**kwargs)
        super_result = super()._serialize(**kwargs)
        super_result['subtitle'] = '%s %s, %s' % (_('(moving)'), result['title'], result['subtitle'])
        result.update(super_result)"""
        result = super()._serialize(**kwargs)
        result['dynamic'] = True
        return result

    def register_change(self, force=False):
        pass

    def serialize_position(self):
        custom_location = self.get_custom_location()
        if custom_location is None:
            return {
                'available': False,
                'id': self.pk,
                'title': self.title,
                'subtitle': '%s %s, %s' % (_('currently unavailable'), _('(moving)'), self.subtitle)
            }
        result = custom_location.serialize(simple_geometry=True)
        result.update({
            'available': True,
            'id': self.pk,
            'slug': self.slug,
            'coordinates': custom_location.pk,
            'icon': self.get_icon(),
            'title': self.title,
            'subtitle': '%s %s%s, %s' % (
                _('(moving)'),
                ('%s, ' % self.subtitle) if self.describing_groups else '',
                result['title'],
                result['subtitle']
            ),
        })
        return result

    def get_custom_location(self):
        if not self.position_secret:
            return None
        try:
            return Position.objects.get(secret=self.position_secret).get_custom_location()
        except Position.DoesNotExist:
            return None

    def details_display(self, editor_url=True, **kwargs):
        result = super().details_display(**kwargs)
        if editor_url:
            result['editor_url'] = reverse('editor.dynamic_locations.edit', kwargs={'pk': self.pk})
        return result


def get_position_secret():
    return get_random_string(32, string.ascii_letters+string.digits)


def get_position_api_secret():
    return get_random_string(64, string.ascii_letters+string.digits)


class Position(CustomLocationProxyMixin, models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(_('name'), max_length=32)
    secret = models.CharField(_('secret'), unique=True, max_length=32, default=get_position_secret)
    last_coordinates_update = models.DateTimeField(_('last coordinates update'), null=True)
    timeout = models.PositiveSmallIntegerField(_('timeout (in seconds)'), default=0, help_text=_('0 for no timeout'))
    coordinates_id = models.CharField(_('coordinates'), null=True, max_length=48)
    api_secret = models.CharField(_('api secret'), max_length=64, default=get_position_api_secret)

    can_search = True
    can_describe = False

    coordinates = LocationById()

    class Meta:
        verbose_name = _('Dynamic position')
        verbose_name_plural = _('Dynamic position')
        default_related_name = 'dynamic_positions'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.timeout and self.last_coordinates_update:
            end_time = self.last_coordinates_update + timedelta(seconds=self.timeout)
            if timezone.now() >= end_time:
                self.cordinates = None
                self.last_coordinates_update = end_time

    def get_custom_location(self):
        return self.coordinates

    @classmethod
    def user_has_positions(cls, user):
        if not user.is_authenticated:
            return False
        cache_key = 'user_has_positions:%d' % user.pk
        result = cache.get(cache_key, None)
        if result is None:
            result = cls.objects.filter(owner=user).exists()
            cache.set(cache_key, result, 600)
        return result

    def serialize_position(self):
        custom_location = self.get_custom_location()
        if custom_location is None:
            return {
                'id': 'p:%s' % self.secret,
                'slug': 'p:%s' % self.secret,
                'available': False,
                'icon': 'my_location',
                'title': self.name,
                'subtitle': _('currently unavailable'),
            }
        result = custom_location.serialize(simple_geometry=True)
        result.update({
            'available': True,
            'id': 'p:%s' % self.secret,
            'slug': 'p:%s' % self.secret,
            'coordinates': custom_location.pk,
            'icon': 'my_location',
            'title': self.name,
            'subtitle': '%s, %s, %s' % (
                _('Position'),
                result['title'],
                result['subtitle']
            ),
        })
        return result

    @property
    def slug(self):
        return 'p:%s' % self.secret

    def serialize(self, *args, **kwargs):
        return {
            'dynamic': True,
            'id': 'p:%s' % self.secret,
            'slug': 'p:%s' % self.secret,
            'icon': 'my_location',
            'title': self.name,
            'subtitle': _('Position'),
        }

    def get_geometry(self, *args, **kwargs):
        return None

    level_id = None

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete('user_has_positions:%d' % self.owner_id))

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            super().delete(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete('user_has_positions:%d' % self.owner_id))
