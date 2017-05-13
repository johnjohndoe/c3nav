from django.conf import settings
from django.db import models
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import JOIN_STYLE
from shapely.ops import cascaded_union

from c3nav.mapdata.models.base import EditorFormMixin
from c3nav.mapdata.models.locations import SpecificLocation
from c3nav.mapdata.render.svg import SVGImage
from c3nav.mapdata.utils.misc import get_dimensions


class Section(SpecificLocation, EditorFormMixin, models.Model):
    """
    A map section like a level
    """
    name = models.SlugField(_('section name'), unique=True, max_length=50)
    altitude = models.DecimalField(_('section altitude'), null=False, unique=True, max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = _('Section')
        verbose_name_plural = _('Sections')
        default_related_name = 'sections'
        ordering = ['altitude']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def lower(self):
        return Section.objects.filter(altitude__lt=self.altitude).order_by('altitude')

    def higher(self):
        return Section.objects.filter(altitude__gt=self.altitude).order_by('altitude')

    def _serialize(self, section=True, **kwargs):
        result = super()._serialize(**kwargs)
        result['name'] = self.name
        result['altitude'] = float(str(self.altitude))
        return result

    def render_svg(self):
        width, height = get_dimensions()
        svg = SVGImage(width=width, height=height, scale=settings.RENDER_SCALE)

        building_geometries = cascaded_union(tuple(b.geometry for b in self.buildings.all()))

        spaces = self.spaces.all()
        space_levels = {
            'upper': [],
            'lower': [],
            '': [],
        }
        for space in spaces:
            space_levels[space.level].append(space)
        space_geometries = {
            level: cascaded_union(tuple((s.geometry.difference(building_geometries) if s.outside else s.geometry)
                                        for s in level_spaces))
            for level, level_spaces in space_levels.items()}

        hole_geometries = cascaded_union(tuple(h.geometry for h in self.holes.all()))
        hole_geometries = hole_geometries.intersection(space_geometries[''])
        hole_svg = svg.add_geometry(hole_geometries, defid='holes')
        hole_mask = svg.add_mask(hole_svg, inverted=True, defid='holes-mask')

        lower_spaces_by_color = {}
        for space in space_levels['lower']:
            lower_spaces_by_color.setdefault(space.get_color(), []).append(space)
        for i, (color, color_spaces) in enumerate(lower_spaces_by_color.items()):
            geometries = cascaded_union(tuple(space.geometry for space in color_spaces))
            space_lower_svg = svg.add_geometry(geometries, defid='spaces-lower-'+str(i))
            svg.use_geometry(space_lower_svg, fill_color=color or '#d1d1d1')

        # draw space background
        door_geometries = cascaded_union(tuple(d.geometry for d in self.doors.all()))
        section_geometry = cascaded_union((space_geometries[''], building_geometries, door_geometries))
        section_svg = svg.add_geometry(section_geometry, defid='section')
        svg.use_geometry(section_svg, fill_color='#d1d1d1', mask=hole_mask)

        # color in spaces
        spaces_by_color = {}
        for space in space_levels['']:
            spaces_by_color.setdefault(space.get_color(), []).append(space)
        spaces_by_color.pop(None, None)
        for i, (color, color_spaces) in enumerate(spaces_by_color.items()):
            geometries = cascaded_union(tuple(space.geometry for space in color_spaces))
            space_svg = svg.add_geometry(geometries, defid='spaces-color-' + str(i))
            svg.use_geometry(space_svg, fill_color=color or '#d1d1d1')

        # calculate walls
        wall_geometry = building_geometries.difference(space_geometries['']).difference(door_geometries)
        wall_svg = svg.add_geometry(wall_geometry, 'walls')
        accessible_mask = svg.add_mask(section_svg, wall_svg, hole_svg, subtract=True, defid='accessible')

        # draw wall shadow
        wall_dilated_geometry = wall_geometry.buffer(0.7, join_style=JOIN_STYLE.mitre)
        wall_dilated_svg = svg.add_geometry(wall_dilated_geometry, 'wall-shadows')
        svg.use_geometry(wall_dilated_svg, fill_color='rgba(0, 0, 0, 0.1)', mask=accessible_mask, filter='wallblur')

        # draw walls
        svg.use_geometry(wall_svg, fill_color='#929292')
        svg.use_geometry(wall_svg, stroke_color='#333333', stroke_width=0.07)

        # draw doors
        door_geometries = cascaded_union(tuple(d.geometry for d in self.doors.all()))
        door_geometries = door_geometries.difference(space_geometries[''])
        door_svg = svg.add_geometry(door_geometries, defid='doors')
        svg.use_geometry(door_svg, fill_color='#ffffff', stroke_color='#929292', stroke_width=0.07)

        # draw upper spaces
        upper_spaces_by_color = {}
        for space in space_levels['upper']:
            upper_spaces_by_color.setdefault(space.get_color(), []).append(space)
        for i, (color, color_spaces) in enumerate(upper_spaces_by_color.items()):
            geometries = cascaded_union(tuple(space.geometry for space in color_spaces))
            space_upper_svg = svg.add_geometry(geometries, defid='spaces-upper-' + str(i))
            svg.use_geometry(space_upper_svg, fill_color=color or '#d1d1d1')

        return svg.get_xml()
