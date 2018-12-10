import argparse
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.mapdata.models import AccessRestriction, Level, Source
from c3nav.mapdata.render.engines import get_engine, get_engine_filetypes
from c3nav.mapdata.render.renderer import MapRenderer


class Command(BaseCommand):
    help = 'render the map'

    @staticmethod
    def levels_value(value):
        if value == '*':
            return Level.objects.filter(on_top_of__isnull=True)

        values = set(v for v in value.split(',') if v)
        levels = Level.objects.filter(on_top_of__isnull=True, short_label__in=values)

        not_found = values - set(level.short_label for level in levels)
        if not_found:
            raise argparse.ArgumentTypeError(
                ungettext_lazy('Unknown level: %s', 'Unknown levels: %s', len(not_found)) % ', '.join(not_found)
            )

        return levels

    @staticmethod
    def permissions_value(value):
        if value == '*':
            return AccessRestriction.objects.all()
        if value == '0':
            return ()

        values = set(v for v in value.split(',') if v)
        permissions = AccessRestriction.objects.all().filter(pk__in=values)

        not_found = values - set(str(permission.pk) for permission in permissions)
        if not_found:
            raise argparse.ArgumentTypeError(
                ungettext_lazy('Unknown access restriction: %s',
                               'Unknown access restrictions: %s', len(not_found)) % ', '.join(not_found)
            )

        return permissions

    @staticmethod
    def scale_value(value):
        try:
            value = float(value)
        except (ValueError, TypeError):
            raise argparse.ArgumentTypeError(_('Invalid zoom'))

        if not (0 < value <= 32):
            raise argparse.ArgumentTypeError(_('Zoom has to be between 0 and 32'))

        return value

    def add_arguments(self, parser):
        parser.add_argument('filetype', type=str, choices=get_engine_filetypes(),
                            help=_('filetype to render'))
        parser.add_argument('--levels', default='*', type=self.levels_value,
                            help=_('levels to render, e.g. 0,1,2 or * for all levels (default)'))
        parser.add_argument('--permissions', default='0', type=self.permissions_value,
                            help=_('permissions, e.g. 2,3 or * for all permissions or 0 for none (default)'))
        parser.add_argument('--full-levels', action='store_const', const=True, default=False,
                            help=_('render all levels completely'))
        parser.add_argument('--no-center', action='store_const', const=True, default=False,
                            help=_('do not center the output'))
        parser.add_argument('--scale', default=1, type=self.scale_value,
                            help=_('scale (from 1 to 32), only relevant for image renderers'))
        parser.add_argument('--minx', default=None, type=float,
                            help=_('minimum x coordinate, everthing left of it will be cropped'))
        parser.add_argument('--miny', default=None, type=float,
                            help=_('minimum y coordinate, everthing below it will be cropped'))
        parser.add_argument('--maxx', default=None, type=float,
                            help=_('maximum x coordinate, everthing right of it will be cropped'))
        parser.add_argument('--maxy', default=None, type=float,
                            help=_('maximum y coordinate, everthing above it will be cropped'))
        parser.add_argument('--min-width', default=None, type=float,
                            help=_('ensure that all objects are at least this thick'))
        parser.add_argument('--name', default=None, type=str,
                            help=_('override filename'))

    def handle(self, *args, **options):
        (minx, miny), (maxx, maxy) = Source.max_bounds()
        if options['minx'] is not None:
            minx = options['minx']
        if options['miny'] is not None:
            miny = options['miny']
        if options['maxx'] is not None:
            maxx = options['maxx']
        if options['maxy'] is not None:
            maxy = options['maxy']

        if minx >= maxx:
            raise CommandError(_('minx has to be lower than maxx'))
        if miny >= maxy:
            raise CommandError(_('miny has to be lower than maxy'))

        for level in options['levels']:
            renderer = MapRenderer(level.pk, minx, miny, maxx, maxy, access_permissions=options['permissions'],
                                   scale=options['scale'], full_levels=options['full_levels'],
                                   min_width=options['min_width'])

            name = options['name'] or ('level_%s' % level.short_label)
            filename = os.path.join(settings.RENDER_ROOT,
                                    '%s.%s' % (name, options['filetype']))

            render = renderer.render(get_engine(options['filetype']), center=not options['no_center'])
            data = render.render(filename)
            if isinstance(data, tuple):
                other_data = data[1:]
                data = data[0]
            else:
                other_data = ()

            open(filename, 'wb').write(data)
            for filename, data in other_data:
                open(filename, 'wb').write(data)
